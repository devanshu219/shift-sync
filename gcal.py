"""
Google Calendar helpers.

Signs in with a Google service account whose JSON key comes from the
GCAL_SERVICE_KEY secret. Your calendar must be shared with the service
account's email address ("Make changes to events").

Safety: every event written here carries a private "managedBy" tag, and only
tagged events are ever listed, updated or deleted.
"""

import hashlib
import json
import logging
import os
from datetime import date, datetime, time

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

log = logging.getLogger("sync.gcal")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
RETRIES = 3  # Google API calls retry on temporary errors (429 / 5xx)

service_account_email = ""


def get_service():
    """Build a Google Calendar client, or return None with a clear message."""
    global service_account_email
    raw = os.environ.get("GCAL_SERVICE_KEY") or ""
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        log.error("GCAL_SERVICE_KEY is not valid. Open the downloaded .json key "
                  "file, copy ALL of it (from the first { to the last }), and "
                  "save it again as the GCAL_SERVICE_KEY secret.")
        return None
    if info.get("type") != "service_account" or "client_email" not in info:
        log.error("GCAL_SERVICE_KEY is not a service-account key. Create a JSON "
                  "key for the service account and paste the whole file.")
        return None
    service_account_email = info["client_email"]
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def check_calendar(service):
    """Return the calendar id if this account can write to it, else None."""
    cal_id = config.CALENDAR_ID
    try:
        meta = service.calendars().get(calendarId=cal_id).execute(num_retries=RETRIES)
        log.info("Using calendar %r.", meta.get("summary", cal_id))
        return cal_id
    except HttpError as err:
        log.error(
            "Cannot reach your calendar (HTTP %s). Check two things: (1) the "
            "CALENDAR_ID secret is the Calendar ID from Google Calendar > "
            "Settings > your calendar > Integrate calendar; (2) that calendar "
            "is shared with %s with 'Make changes to events'.",
            err.resp.status, service_account_email or "the service account email")
        return None


def make_event_id(source, start_dt):
    """Same shift start time -> same event id, so re-runs never duplicate."""
    key = f"{source}|{start_dt.strftime('%Y%m%dT%H%M')}"
    return source + hashlib.sha1(key.encode()).hexdigest()


def event_start(ev, tz):
    """Start of a calendar event as a datetime in `tz` (None if unknown)."""
    start = ev.get("start") or {}
    try:
        if start.get("dateTime"):
            return datetime.fromisoformat(start["dateTime"]).astimezone(tz)
        if start.get("date"):
            return datetime.combine(date.fromisoformat(start["date"]), time.min, tzinfo=tz)
    except ValueError:
        pass
    return None


def list_managed_events(service, calendar_id, source=config.SOURCE):
    """Return {event_id: event} for events this system created for `source`."""
    found = {}
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                privateExtendedProperty=[
                    f"managedBy={config.MANAGED_TAG}",
                    f"source={source}",
                ],
                showDeleted=False,
                singleEvents=True,
                maxResults=2500,
                pageToken=page_token,
            )
            .execute(num_retries=RETRIES)
        )
        for ev in resp.get("items", []):
            found[ev["id"]] = ev
        page_token = resp.get("nextPageToken")
        if not page_token:
            return found


def upsert_event(service, calendar_id, body):
    """Create the event, or update it in place if its id already exists."""
    try:
        service.events().insert(calendarId=calendar_id, body=body).execute(num_retries=RETRIES)
        return "created"
    except HttpError as err:
        if err.resp.status == 409:  # id already exists -> update in place
            service.events().update(
                calendarId=calendar_id, eventId=body["id"], body=body
            ).execute(num_retries=RETRIES)
            return "updated"
        raise


def set_private_prop(service, calendar_id, event_id, key, value):
    """Add one private (hidden) key to an event, keeping everything else."""
    ev = service.events().get(calendarId=calendar_id, eventId=event_id).execute(
        num_retries=RETRIES)
    private = dict(((ev.get("extendedProperties") or {}).get("private") or {}))
    private[key] = value
    service.events().patch(calendarId=calendar_id, eventId=event_id,
                           body={"extendedProperties": {"private": private}}).execute(
        num_retries=RETRIES)


def delete_event(service, calendar_id, event_id):
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute(
            num_retries=RETRIES)
    except HttpError as err:
        if err.resp.status in (404, 410):  # already gone
            return
        raise
