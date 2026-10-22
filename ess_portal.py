"""
Rogers Centre shifts via ABI MasterMind ESS.

Two-step login (venue LEGENDSTBJ, then ESS_USER / ESS_PIN), then "View My
Schedule" month grid. Scrapes this month and next. Each shift cell gives the
report time, venue code, opponent code and game time — e.g.

    3:00 pm (RCT)
    PHI (Mon - 7:00PM)

ESS gives no shift END time, so the event end is estimated from the game time.
Credentials come from the environment and are never logged.
"""

import datetime as dt
import logging
import re
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

import config

log = logging.getLogger("sync.ess_portal")
TZ = ZoneInfo(config.TIMEZONE)


class LoginFailed(Exception):
    """ESS rejected the employee number / PIN."""

_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}

# Pull each day cell's report line + event line straight from the grid.
_GRID_JS = """
() => {
  const out = [];
  document.querySelectorAll('td.calendar_day_box').forEach(td => {
    const det = td.querySelector('.day_details');
    if (!det) return;
    let day = '';
    const dm = (td.innerText || '').match(/^\\s*(\\d{1,2})/);
    if (dm) day = dm[1];
    const a = det.querySelector('a');
    const report = a ? a.innerText.trim() : '';
    const evt = det.innerText.replace(a ? a.innerText : '', '').trim();
    if (report) out.push({ day, report, evt });
  });
  return out;
}
"""


def _parse_clock(text):
    """'7:00PM' / '3:00 pm' -> (hour, minute) 24h, or None."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*([ap])\.?m", text, re.I)
    if not m:
        return None
    h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return h, mn


def _click(ctx, selectors, label):
    for page in [p for p in ctx.pages if not p.is_closed()]:
        for fr in page.frames:
            for sel in selectors:
                try:
                    el = fr.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        return True
                except Exception:
                    continue
    log.warning("ESS: could not find %s", label)
    return False


def _parse_month(page):
    """Read the visible month grid -> list of shift dicts with full dates."""
    body = page.inner_text("body")
    mh = re.search(r"\b(January|February|March|April|May|June|July|August|"
                   r"September|October|November|December)\s+(\d{4})", body)
    if not mh:
        return []
    month, year = _MONTHS[mh.group(1)], int(mh.group(2))
    shifts = []
    for cell in page.evaluate(_GRID_JS):
        if not cell["day"].isdigit():
            continue
        day = int(cell["day"])
        rep = _parse_clock(cell["report"])
        if not rep:
            continue
        try:
            start = dt.datetime(year, month, day, rep[0], rep[1], tzinfo=TZ)
        except ValueError:
            continue
        venue_code = config.ESS_VENUE_CODE
        vm = re.search(r"\(([A-Za-z]+)\)", cell["report"])
        if vm:
            venue_code = vm.group(1)
        evt = cell["evt"]
        em = re.match(r"\s*([A-Za-z]{2,4})\s*\(([A-Za-z]{3})\s*-\s*([0-9:]+\s*[apAP]\.?[mM])\)", evt)
        opp = em.group(1) if em else ""
        game = _parse_clock(em.group(3)) if em else None
        prem = re.search(r"\[\s*([^\]]+?)\s*\]", evt)
        shifts.append({
            "start": start,
            "opponent_code": opp,
            "game_time": game,
            "venue_code": venue_code,
            "premium": prem.group(1) if prem else "",
            "raw_event": evt,
        })
    log.info("ESS: %s %d -> %d shift(s)", mh.group(1), year, len(shifts))
    return shifts


def fetch_rogers_shifts(user, pin):
    """Log in and scrape this month + next. Raises on failure (so the caller
    knows not to delete anything)."""
    all_shifts = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            log.info("ESS: logging in ...")
            page.goto(config.ESS_LOGIN_URL, wait_until="networkidle", timeout=60000)
            page.fill("#input_venue", config.ESS_VENUE_ID)
            page.click('input[value="Submit"], #VenueForm input[type=button]')
            page.wait_for_selector("#LoginId", timeout=30000)
            page.fill("#LoginId", user)
            page.fill("#PIN", pin)
            page.click('#loginButton, input[value="Log In"]')
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(2000)
            if page.query_selector("#PIN"):
                raise LoginFailed()

            if not _click(ctx, ['a:has-text("View My Schedule")', 'a:has-text("My Schedule")',
                                'a:has-text("Schedule")'], "View My Schedule"):
                raise RuntimeError("ESS: 'View My Schedule' link not found")
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(2500)

            for _ in range(2):  # this month + next
                for s in _parse_month(page):
                    all_shifts[s["start"].isoformat()] = s
                if not _click(ctx, ['a:has-text("Next")', 'input[value*="Next"]',
                                    'a[title*="Next"]'], "Next month"):
                    break
                page.wait_for_load_state("networkidle", timeout=60000)
                page.wait_for_timeout(2500)
        finally:
            browser.close()
    return list(all_shifts.values())


def estimate_end(shift):
    """ESS has no end time — estimate from the game time (game + 4h), else +5h."""
    if shift.get("game_time"):
        gh, gm = shift["game_time"]
        game = shift["start"].replace(hour=gh, minute=gm)
        if game < shift["start"]:
            game = shift["start"]
        return game + dt.timedelta(hours=4)
    return shift["start"] + dt.timedelta(hours=5)


def team_name(code):
    return config.MLB_TEAMS.get(code.upper(), code)


def build_summary(shift):
    """e.g. 'Jays vs Phillies, 3:00 pm @RogersCentre'."""
    start = shift["start"]
    h = start.hour % 12 or 12
    clock = f"{h}:{start.minute:02d} {'am' if start.hour < 12 else 'pm'}"
    if shift["opponent_code"]:
        title = f"Jays vs {team_name(shift['opponent_code'])}"
    else:
        title = "Rogers Shift"
    return f"{title}, {clock} @{config.ESS_VENUE_CODE}"


def build_description(shift):
    lines = ["Synced from ABI MasterMind ESS (Rogers Centre)."]
    if shift["opponent_code"]:
        lines.append(f"Game: vs {team_name(shift['opponent_code'])} ({shift['opponent_code']})")
    if shift.get("game_time"):
        gh, gm = shift["game_time"]
        ampm = "am" if gh < 12 else "pm"
        lines.append(f"Game time: {gh % 12 or 12}:{gm:02d} {ampm}")
    lines.append(f"Venue: {config.ESS_VENUE_NAME}")
    if shift.get("premium"):
        lines.append(f"Premium: {shift['premium']}")
    lines.append("Note: shift end time is estimated (ESS only publishes the report time).")
    return "\n".join(lines)
