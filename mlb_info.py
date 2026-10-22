"""
Blue Jays game info from the free MLB Stats API (statsapi.mlb.com).

Provides the exact first-pitch time + matchup for a date range (one request),
and the roof status for a single game (only meaningful on game day).
No API key required.
"""

import datetime as dt
import logging
from zoneinfo import ZoneInfo

import requests

import config

log = logging.getLogger("sync.mlb_info")
TZ = ZoneInfo(config.TIMEZONE)

BLUE_JAYS_ID = 141
ROGERS_CENTRE = "Rogers Centre"
SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
LIVE_URL = "https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"

# Hours before first pitch to start checking the roof (it isn't decided earlier).
ROOF_CHECK_LEAD_HOURS = 12


def short_team(full_name):
    """'Philadelphia Phillies' -> 'Phillies'."""
    return full_name.split()[-1] if full_name else full_name


def get_home_games(start_date, end_date):
    """One request -> {date_iso: {game_dt, away, gamePk}} for Jays HOME games."""
    params = {
        "sportId": 1,
        "teamId": BLUE_JAYS_ID,
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
    }
    try:
        r = requests.get(SCHEDULE_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as err:
        log.warning("MLB schedule fetch failed (%s).", err)
        return {}
    games = {}
    for d in data.get("dates", []):
        for g in d.get("games", []):
            if g.get("teams", {}).get("home", {}).get("team", {}).get("id") != BLUE_JAYS_ID:
                continue
            if g.get("venue", {}).get("name") != ROGERS_CENTRE:
                continue  # e.g. spring training in Florida
            try:
                gd = dt.datetime.fromisoformat(
                    g["gameDate"].replace("Z", "+00:00")).astimezone(TZ)
            except Exception:
                continue
            away = g["teams"]["away"]["team"].get("name", "")
            games[gd.date().isoformat()] = {
                "game_dt": gd, "away": short_team(away), "gamePk": g.get("gamePk")}
    log.info("MLB: found %d Jays home game(s) in range.", len(games))
    return games


def should_check_roof(game_dt, now):
    """True when we're inside the ~12h-before-first-pitch window (and not past)."""
    if not game_dt:
        return False
    return (game_dt - dt.timedelta(hours=ROOF_CHECK_LEAD_HOURS)) <= now <= (
        game_dt + dt.timedelta(hours=6))


def get_roof_status(game_pk):
    """'Open' / 'Closed' / None (unknown). Only reliable on game day."""
    try:
        r = requests.get(LIVE_URL.format(pk=game_pk), timeout=20)
        r.raise_for_status()
        cond = (r.json().get("gameData", {}).get("weather", {}).get("condition") or "").lower()
    except Exception as err:
        log.warning("MLB roof fetch failed (%s).", err)
        return None
    if not cond:
        return None
    if "roof closed" in cond or "dome" in cond:
        return "Closed"
    return "Open"


def rogers_centre_game_near(today, days_ahead):
    """True if the Jays play at Rogers Centre between 3 days ago and
    `days_ahead` days from now (baseball season), False if not, None if the
    MLB schedule can't be reached."""
    params = {
        "sportId": 1,
        "teamId": BLUE_JAYS_ID,
        "startDate": (today - dt.timedelta(days=3)).isoformat(),
        "endDate": (today + dt.timedelta(days=days_ahead)).isoformat(),
    }
    try:
        r = requests.get(SCHEDULE_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as err:
        log.warning("MLB schedule check failed (%s).", err)
        return None
    return any(g.get("venue", {}).get("name") == ROGERS_CENTRE
               for d in data.get("dates", []) for g in d.get("games", []))
