"""
Shift Sync: copies your MLSE and Rogers Centre work shifts into a Google
Calendar. Each source is optional and runs independently: a problem with one
never stops the other.

MLSE, every run:
  1. Reads your personal MLSE calendar feed (shift times).
  2. Adds, moves or removes "MLSE Shift" events in your Google Calendar.
  3. Only when needed, logs in to MLSE WorkForce to add the event name, venue
     and role to upcoming shifts. A brand-new shift gets its details on the
     NEXT run, so the login happens as rarely as possible.

Rogers Centre: see rogers.py.

Built-in safety:
  * Only events this system created (tagged) are ever touched.
  * A broken or empty feed never deletes anything.
  * Shifts that already happened are never deleted.
  * If the feed suddenly shows no upcoming shifts, nothing is deleted.
  * Passwords and keys come from GitHub secrets and are never printed.

Exit codes: 0 = OK, 1 = something broke (retried once), 2 = a setup problem
(missing secret, bad key, calendar not shared), 3 = MLSE or ESS rejected the
login.
GitHub emails you when a run ends with anything other than 0.
"""

import datetime as dt
import hashlib
import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar

import config
import gcal
import mlse_portal
import rogers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync")

TZ = ZoneInfo(config.TIMEZONE)
OK, FAILED, LOGIN_FAILED = config.OK, config.FAILED, config.LOGIN_FAILED
SETUP_PROBLEM, DETAILS_PROBLEM = config.SETUP_PROBLEM, config.DETAILS_PROBLEM

# A plain ✅ / ❌ checklist, shown on the GitHub run page (Summary tab) and at
# the end of the log, so setup problems are easy to spot.
CHECKS = []


def check(name, ok, note=""):
    """ok: True = ✅, False = ❌, None = ⏭️ (not set up / not needed)."""
    CHECKS.append((name, ok, note))


def write_summary():
    icon = {True: "✅", False: "❌", None: "⏭️"}
    log.info("Checklist:")
    for name, ok, note in CHECKS:
        log.info("  %s %s%s", icon[ok], name, f" ({note})" if note else "")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    rows = [f"| {icon[ok]} | {name} | {note} |" for name, ok, note in CHECKS]
    with open(path, "a") as f:
        f.write("## Shift Sync checklist\n\n| | Check | Note |\n|---|---|---|\n"
                + "\n".join(rows) + "\n")


def check_settings():
    """Fail early, in plain words, if a GitHub secret is missing."""
    has = lambda n: bool((os.environ.get(n) or "").strip())
    for n in ("GCAL_SERVICE_KEY", "CALENDAR_ID"):
        check(f"Secret {n}", has(n), "" if has(n) else "missing: add it in Settings > Secrets")
    for group, names in (("MLSE", ("MLSE_USER", "MLSE_PASS")),
                         ("Rogers", ("ESS_USER", "ESS_PIN"))):
        if not any(has(n) for n in names) and not (group == "MLSE" and has("MLSE_ICS_URL")):
            check(f"{group} secrets", None, "not set up, skipped")
            continue
        for n in names:
            check(f"Secret {n}", has(n), "" if has(n) else "missing")
    mlse_ok = has("MLSE_ICS_URL") or (has("MLSE_USER") and has("MLSE_PASS"))
    missing = [n for n in ("GCAL_SERVICE_KEY", "CALENDAR_ID") if not has(n)]
    if not mlse_ok and not (has("ESS_USER") and has("ESS_PIN")):
        missing.append("MLSE_USER + MLSE_PASS (for MLSE) or ESS_USER + ESS_PIN (for Rogers)")
    if missing:
        log.error("Missing GitHub secret(s): %s. Add them in your repository: "
                  "Settings > Secrets and variables > Actions.", ", ".join(missing))
        return False
    if config.MLSE_ICS_URL and not config.MLSE_ICS_URL.startswith("https://"):
        log.error("MLSE_ICS_URL must be the full feed link starting with https:// "
                  "(re-copy it from MLSE WorkForce).")
        return False
    return True


def _as_toronto(value):
    """Normalise an ICS date/datetime to a timezone-aware Toronto datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=TZ)
        return value.astimezone(TZ)
    return datetime.combine(value, dt.time.min, tzinfo=TZ)


def fetch_mlse_shifts(url):
    """Download and parse the MLSE feed. Raises on any failure, so a broken
    feed is never mistaken for "no shifts"."""
    log.info("Fetching MLSE feed ...")
    last_err = None
    resp = None
    # MLSE answers "400 Bad Request" if the same feed is downloaded again
    # within ~30 seconds, so retries wait 35 seconds.
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            break
        except Exception as err:
            last_err = err
            log.warning("Feed attempt %d/3 failed: %s", attempt, type(err).__name__)
            resp = None
            if attempt < 3:
                time.sleep(35)
    if resp is None:
        raise last_err
    if b"BEGIN:VCALENDAR" not in resp.content[:2000]:
        raise ValueError("the feed link did not return a calendar (link wrong or expired)")
    cal = Calendar.from_ical(resp.content)

    shifts = []
    for comp in cal.walk("VEVENT"):
        dtstart = comp.get("dtstart")
        if dtstart is None:
            continue
        start = _as_toronto(dtstart.dt)
        dtend = comp.get("dtend")
        end = _as_toronto(dtend.dt) if dtend is not None else start + dt.timedelta(hours=4)
        shifts.append({
            "uid": str(comp.get("uid", "")).strip(),
            "summary": str(comp.get("summary", "")).strip(),
            "start": start,
            "end": end,
        })
    log.info("Feed parsed: %d shift(s) found.", len(shifts))
    return shifts


def feed_hash(shift):
    """Fingerprint of a shift's times; changes if MLSE moves the shift."""
    raw = shift["start"].isoformat() + "|" + shift["end"].isoformat()
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def build_timeonly_body(shift):
    """A time-only event; details are added on a later run."""
    return {
        "id": gcal.make_event_id(config.SOURCE, shift["start"]),
        "summary": "MLSE Shift",
        "description": (
            "Synced from the MLSE schedule feed (time only).\n"
            f"Feed text: {shift['summary'] or '(none)'}\n"
            "Venue and event details arrive on a later run."
        ),
        "start": {"dateTime": shift["start"].isoformat(), "timeZone": config.TIMEZONE},
        "end": {"dateTime": shift["end"].isoformat(), "timeZone": config.TIMEZONE},
        "extendedProperties": {
            "private": {
                "managedBy": config.MANAGED_TAG,
                "source": config.SOURCE,
                "feedUid": shift["uid"],
                "feedHash": feed_hash(shift),
                "enriched": "no",
            }
        },
    }


def build_enriched_body(shift, detail):
    """The time event upgraded with event name, venue and role."""
    body = build_timeonly_body(shift)
    body["summary"] = mlse_portal.build_summary(detail)
    body["description"] = mlse_portal.build_description(detail)
    priv = body["extendedProperties"]["private"]
    priv["enriched"] = "yes"
    priv["enrichVer"] = config.ENRICH_VERSION
    venue_name = mlse_portal.venue_full(detail.get("venue_code", "")) or detail.get("venue", "")
    location = config.VENUE_LOCATIONS.get(venue_name)
    if location:
        body["location"] = location
    return body



def _stored_feed_url(existing):
    """The feed link this sync found earlier, saved in an event's private data."""
    for ev in existing.values():
        url = ((ev.get("extendedProperties") or {}).get("private") or {}).get("feedUrl")
        if url:
            return url
    return None


def sync_mlse(service, calendar_id):
    user = (os.environ.get("MLSE_USER") or "").strip()
    pw = (os.environ.get("MLSE_PASS") or "").rstrip("\r\n")
    if not config.MLSE_ICS_URL and not (user and pw):
        log.info("MLSE not set up; skipping MLSE.")
        return OK

    existing = gcal.list_managed_events(service, calendar_id)

    # 1. Find the personal calendar feed link: the MLSE_ICS_URL secret if set,
    #    else the one found earlier, else log in once and read it from
    #    My Calendar > Subscribe. A link that stops working is looked up again.
    feed_url = config.MLSE_ICS_URL or _stored_feed_url(existing)
    found_now = False
    shifts = None
    for attempt in (1, 2):
        if not feed_url and user and pw and not found_now:
            try:
                feed_url = mlse_portal.discover_feed_url(user, pw)
            except mlse_portal.LoginFailed:
                check("MLSE login", False, "User ID or password rejected")
                print("::error title=MLSE login failed::Log in by hand at "
                      f"{config.MLSE_PORTAL_URL} (type it, no autofill). If that works, "
                      "save the same password again as the MLSE_PASS secret.")
                return LOGIN_FAILED
            except Exception as err:
                log.error("Couldn't open MLSE to find your calendar link (%s).", err)
                feed_url = None
            found_now = True
        if not feed_url:
            why = ", ".join(mlse_portal.MISSING) or "couldn't open MLSE"
            check("MLSE calendar link", False, f"not found ({why}); retried next run")
            return FAILED
        try:
            shifts = fetch_mlse_shifts(feed_url)  # raises on failure: never "no shifts"
            break
        except Exception as err:
            log.error("MLSE feed failed (%s).", err)
            if config.MLSE_ICS_URL or found_now or not (user and pw):
                check("MLSE calendar link", False, "MLSE didn't return your calendar; "
                      "retried next run")
                return FAILED
            log.info("The saved calendar link stopped working; looking it up again.")
            feed_url = None
    check("MLSE calendar link", True, f"{len(shifts)} shift(s) found"
          + ("; link found automatically" if not config.MLSE_ICS_URL else ""))

    now = datetime.now(TZ)
    desired = {gcal.make_event_id(config.SOURCE, s["start"]): s for s in shifts}
    log.info("Calendar holds %d MLSE event(s); feed has %d shift(s).",
             len(existing), len(desired))

    # 2. Put every shift on the calendar with its time. Unchanged shifts are
    #    left alone, which keeps the details already added to them.
    created = updated = unchanged = deleted = 0
    for eid, shift in desired.items():
        ex = existing.get(eid)
        priv = ((ex.get("extendedProperties") or {}).get("private") or {}) if ex else {}
        if ex and priv.get("feedHash") == feed_hash(shift):
            unchanged += 1
            continue
        result = gcal.upsert_event(service, calendar_id, build_timeonly_body(shift))
        created += result == "created"
        updated += result == "updated"

    # 3. Remove upcoming shifts that MLSE took away. Never past shifts, and
    #    never when the feed looks broken.
    future_feed = [s for s in shifts if s["start"] >= now]
    future_cal = [e for e in existing
                  if e not in desired and (gcal.event_start(existing[e], TZ) or now) >= now]
    if not desired:
        if existing:
            log.warning("Feed returned 0 shifts but %d are on the calendar; keeping "
                        "them (an empty feed is treated as a failure).", len(existing))
    elif not future_feed and len(future_cal) >= 3:
        log.warning("Feed shows no upcoming shifts but %d are on the calendar; "
                    "keeping them in case the feed is incomplete.", len(future_cal))
    else:
        for eid in future_cal:
            gcal.delete_event(service, calendar_id, eid)
            deleted += 1

    log.info("MLSE feed sync: %d created, %d updated, %d unchanged, %d deleted.",
             created, updated, unchanged, deleted)

    # Save an auto-found link on the earliest shift (past shifts are never
    # rewritten), so later runs don't need to log in to find it again.
    if not config.MLSE_ICS_URL and desired and _stored_feed_url(existing) != feed_url:
        keep_id = min(desired, key=lambda e: desired[e]["start"])
        try:
            gcal.set_private_prop(service, calendar_id, keep_id, "feedUrl", feed_url)
        except Exception as err:
            log.warning("Couldn't save the calendar link for next time (%s).", err)

    # 4. Add details. Only shifts that were ALREADY on the calendar before this
    #    run, upcoming, and not yet detailed. No candidates = no login at all.
    today = now.date()
    candidates = {}
    for eid, shift in desired.items():
        ex = existing.get(eid)
        if not ex:
            continue  # brand-new this run; details on the next run
        priv = (ex.get("extendedProperties") or {}).get("private") or {}
        done = (priv.get("enriched") == "yes"
                and priv.get("feedHash") == feed_hash(shift)
                and priv.get("enrichVer") == config.ENRICH_VERSION)
        if done or shift["start"].date() < today:
            continue
        candidates[eid] = shift

    if not candidates:
        log.info("No shifts need details; skipping the MLSE login.")
        check("MLSE login (for event names)", None, "not needed this run")
        return OK

    if not user or not pw:
        log.warning("%d shift(s) need details but MLSE_USER / MLSE_PASS are not "
                    "set; leaving them as time-only.", len(candidates))
        return OK

    max_date = max(s["start"].date() for s in candidates.values())
    log.info("Adding details to %d shift(s) via MLSE WorkForce (through %s) ...",
             len(candidates), max_date)
    try:
        enrich = mlse_portal.fetch_enrichment(user, pw, max_date)
    except mlse_portal.LoginFailed:
        log.error("MLSE login failed: MLSE says the User ID or password is wrong.")
        print("::error title=MLSE login failed::Log in by hand at "
              f"{config.MLSE_PORTAL_URL} (type it, no autofill). If that works, "
              "save the same password again as the MLSE_PASS secret. Shift times "
              "are still syncing.")
        check("MLSE login (for event names)", False, "User ID or password rejected")
        return LOGIN_FAILED
    except Exception as err:
        # Times are already synced. Fail the run visibly rather than skip the
        # details quietly; these shifts stay on the "needs details" list and
        # are retried on every run until they get them.
        log.error("Could not read details from MLSE (%s); times are synced, "
                  "details will be retried next run.", err)
        print("::error title=MLSE event details not added yet::Shift times are in "
              "your calendar. The event names and venues will be added on the next run.")
        check("MLSE event details", False, "couldn't read MLSE this run; retried next run")
        return DETAILS_PROBLEM

    added = 0
    for eid, shift in candidates.items():
        key = (shift["start"].date().isoformat(), shift["start"].strftime("%H:%M"))
        detail = enrich.get(key)
        if detail:
            gcal.upsert_event(service, calendar_id, build_enriched_body(shift, detail))
            added += 1
    log.info("Added details to %d of %d shift(s).", added, len(candidates))
    if added == 0:
        # Logged in, but nothing matched: say why instead of a quiet ✅.
        log.info("Calendar shift times needing details: %s",
                 sorted((s["start"].date().isoformat(), s["start"].strftime("%H:%M"))
                        for s in candidates.values())[:6])
        log.info("Shift times on MLSE's Schedule page: %s", sorted(enrich)[:6])
        missing = ", ".join(dict.fromkeys(mlse_portal.MISSING))
        if missing:
            why = f"couldn't find on MLSE: {missing}"
        elif enrich:
            why = (f"MLSE's Schedule page showed {len(enrich)} shift(s) but none "
                   "matched your calendar's shift times")
        else:
            why = "MLSE's Schedule page showed no shifts"
        diag = mlse_portal.DIAG
        seen = (f"jobs offered: {diag.get('jobs', '?')}; pay periods read: "
                f"{diag.get('periods', 0)}; page held: {diag.get('page', 'n/a')}")
        if diag.get("sample"):
            seen += f"; rows looked like: {diag['sample']}"
        log.error("No event details added: %s. Retried next run. (%s)", why, seen)
        print(f"::error title=MLSE event details not added::{why}. "
              "Shift times are in your calendar.")
        check("MLSE event details", False, f"{why} | {seen}")
        return DETAILS_PROBLEM
    note = f"details added to {added} of {len(candidates)} shift(s)"
    if added < len(candidates):
        note += " (the rest aren't on MLSE's Schedule page yet)"
    check("MLSE login (for event names)", True, note)
    return OK


def not_set_up_yet():
    """A fresh copy with no secrets at all: stay quiet on the schedule
    (no failure emails every hour) until the person adds their secrets."""
    names = ("GCAL_SERVICE_KEY", "CALENDAR_ID", "MLSE_ICS_URL", "MLSE_USER", "MLSE_PASS",
             "ESS_USER", "ESS_PIN")
    return (os.environ.get("GITHUB_EVENT_NAME") == "schedule"
            and not any((os.environ.get(n) or "").strip() for n in names))


def run():
    if not_set_up_yet():
        log.info("No secrets added yet, so there's nothing to sync. Finish setup, "
                 "then run it by hand once from the Actions tab.")
        check("Setup", None, "no secrets yet; scheduled runs wait quietly")
        return OK
    if not check_settings():
        return SETUP_PROBLEM
    service = gcal.get_service()
    check("Google robot key (GCAL_SERVICE_KEY)", bool(service),
          "" if service else "re-copy the whole .json file")
    if not service:
        return SETUP_PROBLEM
    calendar_id = gcal.check_calendar(service)
    check("Calendar shared with the robot email", bool(calendar_id),
          "" if calendar_id else f"share it with {gcal.service_account_email}, "
          "'Make changes to events', and check CALENDAR_ID")
    if not calendar_id:
        return SETUP_PROBLEM
    codes = []
    for name, sync_source in (("MLSE", sync_mlse), ("Rogers", rogers.sync_rogers)):
        try:
            codes.append(sync_source(service, calendar_id))
        except Exception as err:  # one source must never stop the other
            log.error("%s sync crashed (%s).", name, err)
            codes.append(FAILED)
    rogers_set = all((os.environ.get(n) or "").strip() for n in ("ESS_USER", "ESS_PIN"))
    if rogers_set:
        check("Rogers ESS", codes[1] == OK, {
            OK: "OK; in the off-season it checks at 10 AM and 4 PM",
            LOGIN_FAILED: "employee number or PIN rejected",
        }.get(codes[1], "see the log above"))
    for code in (LOGIN_FAILED, FAILED, DETAILS_PROBLEM):
        if code in codes:
            return code
    return OK


def main():
    log.info("=== Shift Sync starting ===")
    try:
        code = run()
    finally:
        write_summary()
    log.info("=== Done ===" if code == OK else "=== Finished with a problem (see above) ===")
    sys.exit(code)


if __name__ == "__main__":
    main()
