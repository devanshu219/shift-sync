"""
MLSE portal enrichment.

Logs into the WorkForce portal with MLSE_USER / MLSE_PASS, navigates to the
timesheet's "Schedule" tab, and reads the schedule grid (venue, department,
job class, event) for each shift. Pages forward through pay periods until it
has covered every date we still need.

Returns a lookup keyed by (YYYY-MM-DD, "HH:MM") so the sync can match each
calendar shift to its details by date + start time.

Credentials come from the environment and are never logged.
"""

import datetime as dt
import logging
import re

from playwright.sync_api import sync_playwright

import config

log = logging.getLogger("sync.mlse_portal")


class LoginFailed(Exception):
    """MLSE rejected the User ID / password."""


# Pages/buttons the last enrichment couldn't find (shown on the checklist).
MISSING = []
# What the last enrichment saw: jobs offered, pay periods read, and (for an
# empty page) which timesheet rows and filled-in fields existed.
DIAG = {}

# DOM extraction for the Schedule grid (Panel_5). Values live in each cell's
# inner field wrapper `title` (or the input value).
_GRID_JS = """
() => {
  // Schedule rows: MLSE marks them with paycode "MLSE_SCHEDULE". The panel
  // number differs between accounts (Panel_5 on some), so it isn't relied on.
  const all = [...document.querySelectorAll('tr[id^="dataRow|"]')];
  let rows = all.filter(r => (r.getAttribute('paycode') || '') === 'MLSE_SCHEDULE'
                          || r.id.startsWith('dataRow|Panel_5'));
  if (!rows.length) rows = all.filter(r =>
      r.querySelector('[fieldmappingpolicy="MLSE_EVENT"],[fieldmappingpolicy="MLSE_VENUE"]'));
  const cell = (r, pol) => {
    const d = r.querySelector(`[fieldmappingpolicy="${pol}"][title]`)
           || r.querySelector(`input[fieldmappingpolicy="${pol}"]`);
    return d ? (d.getAttribute('title') || d.value || '').trim() : '';
  };
  return rows.map(r => {
    const dt = r.querySelector('[name="work_dt"]');
    return {
      date: dt ? dt.textContent.trim() : '',
      start: cell(r,'START_DTTM'), end: cell(r,'END_DTTM'),
      venue: cell(r,'MLSE_VENUE'), department: cell(r,'MLSE_DEPARTMENT'),
      job_class: cell(r,'MLSE_JOB_CLASS'), event: cell(r,'MLSE_EVENT'),
    };
  }).filter(x => x.venue || x.event || x.start);
}
"""

# What the timesheet holds, for the log when no schedule rows are found.
_PANELS_JS = """
() => {
  const out = {};
  const fields = {};
  document.querySelectorAll('tr[id^="dataRow|"]').forEach(r => {
    const k = r.id.split('|')[1] + ':' + (r.getAttribute('paycode') || '-');
    out[k] = (out[k] || 0) + 1;
    if (!fields[k]) {
      const names = [...r.querySelectorAll('[fieldmappingpolicy]')]
        .filter(e => (e.getAttribute('title') || e.value || '').trim())
        .map(e => e.getAttribute('fieldmappingpolicy'));
      if (names.length) fields[k] = [...new Set(names)].slice(0, 12);
    }
  });
  return {rows: out, filled_fields: fields};
}
"""


def parse_clock(text):
    """'09:30 am' / '5:30 pm' -> 'HH:MM' (24h), or None."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*([ap])m", text.strip(), re.I)
    if not m:
        return None
    h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mn:02d}"


def venue_full(code):
    return config.MLSE_VENUE_NAMES.get(code.strip(), code.strip())


def clean_event(event):
    """'Canada v Bosnia Jun 12/26' -> 'Canada v Bosnia'."""
    return re.sub(r"\s+[A-Z][a-z]{2}\s+\d{1,2}/\d{1,2}\s*$", "", event).strip()


def clean_role(job_class):
    """'Concessions Attendant CCC BMO Gen' -> 'Concessions Attendant'."""
    out = []
    for tok in job_class.split():
        # stop at trailing venue/location codes (all-caps short tokens, 'Gen')
        if tok.isupper() and len(tok) <= 4:
            break
        if tok in ("Gen",):
            break
        out.append(tok)
    return " ".join(out).strip() or job_class.strip()


def _period_bounds(text):
    """'05/31/2026 - 06/13/2026' -> (date start, date end), or (None, None)."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4}).*?(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return None, None
    a = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    b = dt.date(int(m.group(6)), int(m.group(4)), int(m.group(5)))
    return a, b


def _row_to_date(mmdd_text, p_start, p_end):
    """'Fri 06/12' + period bounds -> a date with the right year."""
    m = re.search(r"(\d{1,2})/(\d{1,2})", mmdd_text)
    if not m:
        return None
    mo, da = int(m.group(1)), int(m.group(2))
    for yr in {p_start.year, p_end.year} if p_start and p_end else {dt.date.today().year}:
        try:
            d = dt.date(yr, mo, da)
        except ValueError:
            continue
        if not p_start or (p_start - dt.timedelta(days=2)) <= d <= (p_end + dt.timedelta(days=2)):
            return d
    try:
        return dt.date((p_end or dt.date.today()).year, mo, da)
    except ValueError:
        return None


def _click_any(ctx, selectors, label, timeout=5000):
    for page in [p for p in ctx.pages if not p.is_closed()]:
        for fr in page.frames:
            for sel in selectors:
                try:
                    el = fr.query_selector(sel)
                    if el and el.is_visible():
                        el.click(timeout=timeout)
                        log.info("clicked %s", label)
                        return True
                except Exception:
                    continue
    log.warning("could not find %s", label)
    MISSING.append(label)
    return False


def _loadscreen_frame(page):
    for fr in page.frames:
        if "loadScreen" in fr.url:
            return fr
    return None


def _login(page, user, pw):
    """Log in to WorkForce; raises LoginFailed if the password is rejected."""
    log.info("MLSE: logging in ...")
    page.goto(config.MLSE_PORTAL_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_selector("#password", timeout=30000)
    page.fill("#username", user)
    page.fill("#password", pw)
    page.click("#LogonForm input[type=submit], input[name=Submit], button:has-text('Log In')")
    page.wait_for_load_state("networkidle", timeout=60000)
    if page.query_selector("#password"):
        raise LoginFailed()
    page.wait_for_timeout(2000)


def _assignment_links(ctx):
    """Visible job (assignment) links on MLSE's "pick an assignment" page."""
    for pg in [x for x in ctx.pages if not x.is_closed()]:
        for fr in pg.frames:
            if "AsgnmtPicker" not in fr.url:
                continue
            for sel in ('a:has-text("Timesheet")', 'a:has-text("Schedule")', 'table a'):
                try:
                    links = [e for e in fr.query_selector_all(sel) if e.is_visible()]
                except Exception:
                    links = []
                if links:
                    return links
    return []


def _open_my_calendar(ctx, page, index=0):
    """From the home page to the month calendar, opening job number `index`
    when MLSE asks which job (assignment). Returns how many jobs there are."""
    _click_any(ctx, ['[id^="SCHEDULES.MY_CALENDAR"]',
                     'a[href*="createForEmployeeCalendar"]',
                     'a:has-text("My Calendar")'], "My Calendar")
    page.wait_for_timeout(3500)
    links = _assignment_links(ctx)
    if links:
        log.info("MLSE: %d job(s) to choose from; opening job %d.", len(links), index + 1)
        if index < len(links):
            links[index].click()
            log.info("clicked assignment")
            page.wait_for_timeout(3500)
        return len(links)
    _click_any(ctx, ['a:has-text("Timesheet")', 'a:has-text("Schedule")', 'table a'],
               "assignment")
    page.wait_for_timeout(3500)
    return 1


_FEED_RE = re.compile(r"https://[^\s\"'<>]*ICalFeed\.do\?[^\s\"'<>]+")


def discover_feed_url(user, pw):
    """Log in, open My Calendar > Subscribe, and return the personal calendar
    feed link (or None if it can't be found)."""
    MISSING.clear()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            _login(page, user, pw)
            _open_my_calendar(ctx, page)
            _click_any(ctx, ['div.subscribeButton', '[title="Subscribe Calendar"]',
                             'button:has-text("Subscribe")', 'a:has-text("Subscribe")'],
                       "Subscribe")
            page.wait_for_timeout(3000)
            for pg in [x for x in ctx.pages if not x.is_closed()]:
                for fr in pg.frames:
                    try:
                        values = fr.evaluate(
                            "() => [...document.querySelectorAll('input,textarea')]"
                            ".map(e => e.value || '')"
                            ".concat([...document.querySelectorAll('a[href]')].map(a => a.href))")
                        values.append(fr.content())
                    except Exception:
                        continue
                    for text in values:
                        m = _FEED_RE.search((text or "").replace("&amp;", "&"))
                        if m:
                            log.info("MLSE: found your calendar feed link.")
                            return m.group(0)
            MISSING.append("calendar feed link (My Calendar > Subscribe)")
            log.warning("MLSE: couldn't find the calendar feed link.")
            return None
        finally:
            browser.close()


def _read_schedule(ctx, page, max_date):
    """From the month calendar to the timesheet's Schedule tab; read every
    pay period up to `max_date`. Returns {(iso_date, 'HH:MM'): detail}."""
    result = {}
    _click_any(ctx, ['div.CALENDAR_CATEGORY-SCHEDULE_class',
                     'div[title="Scheduled Time"]', '.items .item'], "a shift")
    page.wait_for_timeout(3000)
    _click_any(ctx, ['a:has-text("Go To Time Sheet")',
                     'button:has-text("Go To Time Sheet")',
                     'input[value*="Time Sheet"]'], "Go To Time Sheet")
    page.wait_for_timeout(4000)
    _click_any(ctx, ['a:has-text("Schedule")', 'span:has-text("Schedule")',
                     'div[role="tab"]:has-text("Schedule")'], "Schedule tab")
    page.wait_for_timeout(4000)

    frame = _loadscreen_frame(page)
    if not frame:
        log.error("MLSE: could not find the timesheet frame.")
        MISSING.append("timesheet Schedule tab")
        return result

    seen_ranges = set()
    for _ in range(config.MLSE_MAX_PERIODS):
        frame = _loadscreen_frame(page) or frame
        try:
            range_text = frame.inner_text(".currentDateText")
        except Exception:
            range_text = ""
        p_start, p_end = _period_bounds(range_text)
        if range_text in seen_ranges:
            break  # navigation didn't advance
        seen_ranges.add(range_text)

        rows = frame.evaluate(_GRID_JS)
        added = 0
        for r in rows:
            d = _row_to_date(r["date"], p_start, p_end)
            t = parse_clock(r["start"])
            if not d or not t:
                continue
            result[(d.isoformat(), t)] = {
                "venue_code": r["venue"],
                "venue": venue_full(r["venue"]),
                "department": r["department"],
                "job_class": r["job_class"],
                "event": r["event"],
                "start": r["start"],
                "end": r["end"],
            }
            added += 1
        log.info("MLSE: period %s -> %d rows (%d usable)", range_text or "?", len(rows), added)
        DIAG["periods"] = DIAG.get("periods", 0) + 1
        if not rows:
            try:
                DIAG["page"] = frame.evaluate(_PANELS_JS)
                log.info("MLSE: timesheet rows on this page: %s", DIAG["page"])
            except Exception:
                pass

        if p_end and p_end >= max_date:
            break
        if not _click_any(ctx, ['button[aria-label="Next Period"]', '.nextDateIcon'],
                          "Next Period"):
            break
        page.wait_for_timeout(3500)
    return result


def fetch_enrichment(user, pw, max_date):
    """Return {(iso_date, 'HH:MM'): detail_dict} covering up to `max_date`.
    Tries each MLSE job (assignment), up to 3, until one has scheduled shifts."""
    result = {}
    MISSING.clear()
    DIAG.clear()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            _login(page, user, pw)
            for job in range(3):
                if job > 0:
                    log.info("MLSE: no scheduled shifts under job %d; trying job %d.",
                             job, job + 1)
                    MISSING.clear()
                    page.goto(config.MLSE_PORTAL_URL, wait_until="networkidle", timeout=60000)
                    if page.query_selector("#password"):
                        _login(page, user, pw)
                    page.wait_for_timeout(2000)
                jobs = _open_my_calendar(ctx, page, job)
                DIAG["jobs"] = jobs
                result.update(_read_schedule(ctx, page, max_date))
                if result or job + 1 >= jobs:
                    break
        finally:
            browser.close()
    log.info("MLSE: collected enrichment for %d shift slots.", len(result))
    return result


def fmt_clock(text):
    """'01:15 pm' -> '1:15PM' (drop leading zero, no space, uppercase)."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*([ap])m", text.strip(), re.I)
    if not m:
        return text.strip()
    return f"{int(m.group(1))}:{m.group(2)}{m.group(3).upper()}M"


def classify_emoji(detail):
    """Pick an emoji for an MLSE shift from the event/venue/department."""
    dept_emoji = config.DEPARTMENT_PREFIX_EMOJI.get((detail.get("department") or "").strip()[:2])
    if dept_emoji:
        return dept_emoji
    text = " ".join([
        detail.get("event", ""), detail.get("venue", ""), detail.get("venue_code", ""),
        detail.get("department", ""), detail.get("job_class", ""),
    ]).lower()
    if (any(k in text for k in ("marlies", "hockey", "nhl", "ahl", "leafs"))
            or re.search(r"\btml\b", text)):
        return "🏒"
    # Before the BMO rule: the Argos and rugby also play at BMO Field.
    if any(k in text for k in ("argos", "argonauts", "cfl")):
        return "🏈"
    if "rugby" in text:
        return "🏉"
    if any(k in text for k in ("fifa", "soccer", "world cup")) or detail.get("venue_code") == "BMO":
        return "⚽"
    if any(k in text for k in ("tempo", "raptors", "basketball", "wnba", "nba")):
        return "🏀"
    if any(k in text for k in ("concert", "tour", "live nation", "music", " band")):
        return "🎵"
    return "📅"


def build_summary(detail):
    """'<emoji>Event, start–end @CODE' (e.g. '⚽Canada v Bosnia, 9:30AM–6:15PM @BMO')."""
    event = clean_event(detail.get("event", "")) or "Shift"
    venue = detail.get("venue_code") or detail.get("venue", "")
    start, end = fmt_clock(detail.get("start", "")), fmt_clock(detail.get("end", ""))
    timing = f"{start}–{end}" if start and end else (start or end)
    summary = f"{classify_emoji(detail)}{event}"
    if timing:
        summary += f", {timing}"
    if venue:
        summary += f" @{venue}"
    return summary


def build_description(detail):
    lines = ["Synced from the MLSE portal schedule."]
    if detail.get("event"):
        lines.append(f"Event: {detail['event']}")
    if detail.get("venue"):
        v = detail["venue"]
        if detail.get("venue_code") and detail["venue_code"] != v:
            v += f" ({detail['venue_code']})"
        lines.append(f"Venue: {v}")
    if detail.get("department"):
        lines.append(f"Department: {detail['department']}")
    if detail.get("job_class"):
        lines.append(f"Job class: {detail['job_class']}")
    if detail.get("start") or detail.get("end"):
        lines.append(f"Scheduled: {detail.get('start','')}–{detail.get('end','')}")
    return "\n".join(lines)
