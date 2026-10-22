"""
Rogers Centre shifts: ABI MasterMind ESS -> Google Calendar.

Each run (when ESS is due, see config "Season detection"):
  1. Logs in to ESS and reads this month's and next month's schedule.
  2. Adds MLB details for game days: opponent, first pitch, and the roof
     status (checked from about 12 hours before first pitch).
  3. Adds, updates or removes Rogers events in the calendar.

Built-in safety (same as MLSE): only tagged events are touched, an empty or
failed scrape deletes nothing, and past shifts are never deleted.
"""

import datetime as dt
import hashlib
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import ess_portal
import gcal
import mlb_info

log = logging.getLogger("sync.rogers")
TZ = ZoneInfo(config.TIMEZONE)
SOURCE = config.ROGERS_SOURCE


def _fmt_ampm(when):
    """datetime -> '7:07PM'."""
    h = when.hour % 12 or 12
    return f"{h}:{when.minute:02d}{'AM' if when.hour < 12 else 'PM'}"


def _ess_game_clock(shift):
    """Game time from ESS ('7:00PM') when MLB data is unavailable."""
    gt = shift.get("game_time")
    if not gt:
        return ""
    gh, gm = gt
    return f"{gh % 12 or 12}:{gm:02d}{'AM' if gh < 12 else 'PM'}"


def _clean_ess_event(text):
    """'ZACH BRYAN CONCERT!!!' -> 'Zach Bryan Concert'."""
    return re.sub(r"!+$", "", text).strip().title()


def _description(shift, away, first_pitch, roof, event_name=""):
    lines = ["Synced from ABI MasterMind ESS + MLB schedule."]
    if away:
        lines.append(f"Game: Blue Jays vs {away}")
    elif event_name:
        lines.append(f"Event: {event_name}")
    if first_pitch:
        lines.append(f"First pitch: {first_pitch}")
    if away:
        lines.append(f"Roof: {roof}")
    lines.append(f"Venue: {config.ESS_VENUE_NAME}")
    if shift.get("premium"):
        lines.append(f"Premium: {shift['premium']}")
    lines.append("Note: end time is estimated (ESS only publishes the report time).")
    return "\n".join(lines)


def ess_due(now):
    """(True/False, reason): should this run log in to ESS?"""
    if config.ROGERS_FORCE_CHECK:
        return True, "ROGERS_FORCE_CHECK is on"
    near = mlb_info.rogers_centre_game_near(now.date(), config.ROGERS_SEASON_LOOKAHEAD_DAYS)
    if near is None:
        return True, "MLB schedule unavailable, checking to be safe"
    if near:
        return True, "baseball season"
    if now.hour in config.ROGERS_OFFSEASON_CHECK_HOURS:
        return True, "daily off-season check"
    return False, "off-season"


def build_body(shift, game, prev, now):
    """Calendar event for one ESS shift (game info from MLB when available)."""
    away = (game["away"] if game else None) or prev.get("away") \
        or ess_portal.team_name(shift["opponent_code"])
    if game:
        first_pitch = _fmt_ampm(game["game_dt"])
        end = game["game_dt"] + dt.timedelta(hours=4)
    else:
        first_pitch = prev.get("firstPitch", "") or _ess_game_clock(shift)
        end = ess_portal.estimate_end(shift)

    # Roof: keep once known; otherwise only ask MLB inside the ~12h window.
    roof = prev.get("roof") or "TBD"
    if roof not in ("Open", "Closed") and game and mlb_info.should_check_roof(game["game_dt"], now):
        roof = mlb_info.get_roof_status(game["gamePk"]) or roof

    event_name = "" if away else _clean_ess_event(shift.get("raw_event", ""))
    clock = _fmt_ampm(shift["start"])
    if away:
        summary = f"⚾Jays vs {away}, {clock} @{config.ESS_VENUE_CODE}"
    elif event_name:
        summary = f"🎵{event_name}, {clock} @{config.ESS_VENUE_CODE}"
    else:
        summary = f"⚾Rogers Shift, {clock} @{config.ESS_VENUE_CODE}"

    body = {
        "id": gcal.make_event_id(SOURCE, shift["start"]),
        "summary": summary,
        "description": _description(shift, away, first_pitch, roof, event_name),
        "location": config.VENUE_LOCATIONS["Rogers Centre"],
        "start": {"dateTime": shift["start"].isoformat(), "timeZone": config.TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": config.TIMEZONE},
        "extendedProperties": {"private": {
            "managedBy": config.MANAGED_TAG, "source": SOURCE,
            "away": away, "firstPitch": first_pitch, "roof": roof}},
    }
    chash = hashlib.sha1((body["summary"] + body["description"] + body["start"]["dateTime"]
                          + body["end"]["dateTime"]).encode()).hexdigest()[:12]
    body["extendedProperties"]["private"]["contentHash"] = chash
    return body


def sync_rogers(service, calendar_id):
    user = (os.environ.get("ESS_USER") or "").strip()
    pin = (os.environ.get("ESS_PIN") or "").strip()
    if not user or not pin:
        log.info("ESS_USER / ESS_PIN not set; skipping Rogers Centre.")
        return config.OK

    now = datetime.now(TZ)
    due, why = ess_due(now)
    if not due:
        log.info("Rogers: %s; next ESS check at %s:00.", why,
                 " or ".join(str(h) for h in config.ROGERS_OFFSEASON_CHECK_HOURS))
        return config.OK
    log.info("Rogers: checking ESS (%s).", why)

    try:
        shifts = ess_portal.fetch_rogers_shifts(user, pin)
    except ess_portal.LoginFailed:
        log.error("ESS login failed: ESS says the employee number or PIN is wrong.")
        print("::error title=Rogers ESS login failed::Log in by hand at "
              f"{config.ESS_LOGIN_URL} (venue {config.ESS_VENUE_ID}). If that works, save "
              "the same employee number and PIN again as ESS_USER and ESS_PIN.")
        return config.LOGIN_FAILED
    except Exception as err:
        log.error("Rogers/ESS failed (%s). Rogers events left untouched.", err)
        return config.FAILED

    existing = gcal.list_managed_events(service, calendar_id, SOURCE)
    game_map = {}
    if shifts:
        dates = [s["start"].date() for s in shifts]
        game_map = mlb_info.get_home_games(min(dates), max(dates))

    desired = {}
    for s in shifts:
        eid = gcal.make_event_id(SOURCE, s["start"])
        prev = ((existing.get(eid, {}).get("extendedProperties") or {}).get("private") or {})
        body = build_body(s, game_map.get(s["start"].date().isoformat()), prev, now)
        desired[eid] = body

    log.info("Rogers: calendar holds %d event(s); ESS shows %d shift(s).",
             len(existing), len(desired))

    created = updated = unchanged = deleted = 0
    for eid, body in desired.items():
        ex = existing.get(eid)
        priv = ((ex.get("extendedProperties") or {}).get("private") or {}) if ex else {}
        if ex and priv.get("contentHash") == body["extendedProperties"]["private"]["contentHash"]:
            unchanged += 1
            continue
        res = gcal.upsert_event(service, calendar_id, body)
        created += res == "created"
        updated += res == "updated"

    # Remove upcoming shifts ESS took away; never past ones, never on an empty scrape.
    if desired:
        for eid, ev in existing.items():
            if eid in desired:
                continue
            start = gcal.event_start(ev, TZ)
            if start and start < now:
                continue
            gcal.delete_event(service, calendar_id, eid)
            deleted += 1
    elif existing:
        log.info("ESS shows no shifts this month or next; keeping the %d Rogers "
                 "event(s) already on the calendar.", len(existing))

    log.info("Rogers sync: %d created, %d updated, %d unchanged, %d deleted.",
             created, updated, unchanged, deleted)
    return config.OK
