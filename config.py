"""
Settings for Shift Sync (MLSE + Rogers Centre).

Nothing personal or secret lives in this file. Your calendar ID, your MLSE
feed link and logins, and your Rogers ESS login all come from GitHub secrets,
so this file is the same for everyone and never needs editing.
"""

import os

# Everything happens in Toronto time.
TIMEZONE = "America/Toronto"

# --- Personal values (read from GitHub secrets at run time) -----------------
CALENDAR_ID = (os.environ.get("CALENDAR_ID") or "").strip()
MLSE_ICS_URL = (os.environ.get("MLSE_ICS_URL") or "").strip()

# --- MLSE WorkForce ---------------------------------------------------------
# Native WorkForce login page (plain User ID + password). Do NOT use any
# "SSO" login page: it uses different credentials.
MLSE_PORTAL_URL = "https://mlse.wta-ca3.wfs.cloud/workforce/Desktop.do"

# How many pay periods (about 2 weeks each) to page forward when looking up
# shift details.
MLSE_MAX_PERIODS = 10

# Venue codes used by MLSE -> full names.
MLSE_VENUE_NAMES = {
    "BMO": "BMO Field",
    "CCC": "Coca-Cola Coliseum",
    "SBA": "Scotiabank Arena",
    "SBArena": "Scotiabank Arena",
    "RC": "Rogers Centre",
}

# Street addresses, so calendar events get a tappable location.
VENUE_LOCATIONS = {
    "Rogers Centre": "1 Blue Jays Way, Toronto, ON M5V 1J1",
    "Scotiabank Arena": "40 Bay St, Toronto, ON M5J 2X2",
    "BMO Field": "170 Princes' Blvd, Toronto, ON M6K 3C3",
    "Coca-Cola Coliseum": "45 Manitoba Dr, Toronto, ON M6K 3C3",
}

# First two digits of the MLSE department number -> title icon. Concerts are
# listed only by the artist's name, so the department is the reliable signal.
# Unlisted prefixes (e.g. 19xxx "General") fall back to keywords in the name.
DEPARTMENT_PREFIX_EMOJI = {
    "10": "🏒",  # Maple Leafs
    "11": "🏒",  # Marlies
    "15": "🏀",  # Raptors
    "16": "🏀",  # Raptors 905
    "17": "🎵",  # "Live": concerts and other live shows
    "20": "⚽",  # TFC
    "22": "⚽",  # TFC II
    "24": "🏈",  # Argonauts
    "32": "⚽",  # FIFA
}

# --- Rogers Centre (ABI MasterMind ESS, employer Legends Hospitality) --------
ESS_LOGIN_URL = "https://ess.abimm.com/ABIMM_ASP/Request.aspx"
ESS_VENUE_ID = "LEGENDSTBJ"
ESS_VENUE_NAME = "Rogers Centre"
ESS_VENUE_CODE = "RogersCentre"

# Season detection (automatic, from the MLB schedule; nothing to update yearly):
#  * If the Jays play at Rogers Centre within this many days, ESS is checked
#    on every run.
#  * Otherwise (off-season) ESS is checked only on runs in these Toronto
#    hours, so concerts and other events are still caught once or twice a day.
ROGERS_SEASON_LOOKAHEAD_DAYS = 45
ROGERS_OFFSEASON_CHECK_HOURS = (10, 16)
# Set the ROGERS_FORCE_CHECK secret to 1 to check ESS on every run regardless.
ROGERS_FORCE_CHECK = (os.environ.get("ROGERS_FORCE_CHECK") or "").strip() == "1"

# MLB opponent codes -> team names (fallback when the MLB schedule is down).
MLB_TEAMS = {
    "ARI": "Diamondbacks", "ATL": "Braves", "BAL": "Orioles", "BOS": "Red Sox",
    "CHC": "Cubs", "CWS": "White Sox", "CHW": "White Sox", "CIN": "Reds",
    "CLE": "Guardians", "COL": "Rockies", "DET": "Tigers", "HOU": "Astros",
    "KC": "Royals", "KCR": "Royals", "LAA": "Angels", "LAD": "Dodgers",
    "MIA": "Marlins", "MIL": "Brewers", "MIN": "Twins", "NYM": "Mets",
    "NYY": "Yankees", "OAK": "Athletics", "ATH": "Athletics", "PHI": "Phillies",
    "PIT": "Pirates", "SD": "Padres", "SDP": "Padres", "SEA": "Mariners",
    "SF": "Giants", "SFG": "Giants", "STL": "Cardinals", "TB": "Rays",
    "TBR": "Rays", "TEX": "Rangers", "TOR": "Blue Jays", "WSH": "Nationals",
    "WAS": "Nationals",
}

# --- Internal ---------------------------------------------------------------
# Exit codes: GitHub emails you when a run ends with anything other than 0.
# 2 (setup problem) and 3 (login rejected) are not retried by the workflow.
OK, FAILED, SETUP_PROBLEM, LOGIN_FAILED = 0, 1, 2, 3

# Tag stamped on every event this system creates. It only ever reads, updates
# or deletes events carrying this tag, so events you add by hand are safe.
MANAGED_TAG = "mlse-shift-sync"
SOURCE = "mlse"
ROGERS_SOURCE = "rogers"

# Bump when the event title/description format changes; upcoming shifts are
# then refreshed on the next run.
ENRICH_VERSION = "1"
