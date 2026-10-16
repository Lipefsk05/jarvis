"""Google Calendar over its REST API, one service account for every calendar shared with it.

The code in here only talks HTTP: the session is injected (an `AuthorizedSession` in production, a fake in
tests), so nothing else in the project needs `google-auth` or `requests` to be imported."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"
TIMEOUT_S = 15
MAX_RESULTS = 100


class CalendarError(Exception):
    """The calendar could not be read or changed. `status` is the HTTP code, 0 when the network failed."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class Session(Protocol):
    def request(self, method: str, url: str, **kwargs): ...


@dataclass(frozen=True)
class Event:
    id: str
    calendar: str          # the calendar id (an e-mail), not the label
    title: str
    start: datetime        # timezone-aware; an all-day event starts at 00:00 of its first day
    end: datetime
    all_day: bool = False
    location: str = ""


def new_event_id() -> str:
    """An id we choose ourselves (lowercase hex is valid), so an undo button can carry it."""
    return "jv" + uuid.uuid4().hex


def _parse_when(node: dict, zone) -> tuple[datetime, bool]:
    if "dateTime" in node:
        return datetime.fromisoformat(node["dateTime"].replace("Z", "+00:00")).astimezone(zone), False
    day = datetime.fromisoformat(node["date"])
    return day.replace(tzinfo=zone), True


def event_from_api(raw: dict, calendar: str, zone) -> Event | None:
    """An Event from one item of the API, or None for what we do not show (cancelled, malformed)."""
    try:
        if raw.get("status") == "cancelled":
            return None
        start, all_day = _parse_when(raw["start"], zone)
        end, _ = _parse_when(raw["end"], zone)
        return Event(raw["id"], calendar, (raw.get("summary") or "(sem título)").strip(), start, end, all_day,
                     (raw.get("location") or "").strip())
    except (KeyError, ValueError, TypeError):
        return None


class GoogleCalendar:
    def __init__(self, session: Session, zone) -> None:
        self._session = session
        self._zone = zone

    def _call(self, method: str, calendar: str, path: str = "", ok_missing: bool = False, **kwargs) -> dict:
        url = f"{API}/calendars/{quote(calendar, safe='')}/events{path}"
        try:
            response = self._session.request(method, url, timeout=TIMEOUT_S, **kwargs)
        except Exception as exc:  # network, DNS, token refresh: never leak the library's error type
            raise CalendarError(f"sem conexão com o Google Calendar ({type(exc).__name__})") from exc
        status = response.status_code
        if ok_missing and status in (404, 410):
            return {}
        if status >= 400:
            raise CalendarError(f"o Google respondeu {status}", status)
        if status == 204 or not response.content:
            return {}
        return response.json()

    def list_events(self, calendar: str, start: datetime, end: datetime) -> list[Event]:
        """Events that touch [start, end), recurring ones already expanded, in order."""
        data = self._call("GET", calendar, params={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": MAX_RESULTS, "timeZone": str(self._zone),
        })
        events = (event_from_api(item, calendar, self._zone) for item in data.get("items", []))
        return [e for e in events if e is not None]

    def insert(self, calendar: str, title: str, start: datetime, end: datetime, location: str = "",
               event_id: str | None = None) -> Event:
        body = {
            "id": event_id or new_event_id(), "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": str(self._zone)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(self._zone)},
        }
        if location:
            body["location"] = location
        raw = self._call("POST", calendar, json=body)
        event = event_from_api(raw, calendar, self._zone)
        if event is None:
            raise CalendarError("o Google devolveu um evento que não consegui ler")
        return event

    def move(self, calendar: str, event_id: str, start: datetime, end: datetime) -> Event:
        body = {"start": {"dateTime": start.isoformat(), "timeZone": str(self._zone)},
                "end": {"dateTime": end.isoformat(), "timeZone": str(self._zone)}}
        raw = self._call("PATCH", calendar, f"/{quote(event_id, safe='')}", json=body)
        event = event_from_api(raw, calendar, self._zone)
        if event is None:
            raise CalendarError("o Google devolveu um evento que não consegui ler")
        return event

    def delete(self, calendar: str, event_id: str) -> None:
        """Delete it; an event that is already gone counts as done."""
        self._call("DELETE", calendar, f"/{quote(event_id, safe='')}", ok_missing=True)


def _all_day_body(title: str, day: date, description: str) -> dict:
    body = {"summary": title, "status": "confirmed", "transparency": "transparent",  # a task never makes the day "busy"
            "start": {"date": day.isoformat()}, "end": {"date": (day + timedelta(days=1)).isoformat()}}
    if description:
        body["description"] = description
    return body


def upsert_all_day(self, calendar: str, event_id: str, title: str, day: date, description: str = "") -> None:
    """Create the all-day item, or bring it to this title and day if it exists (a deleted id still counts as taken)."""
    body = _all_day_body(title, day, description)
    try:
        self._call("POST", calendar, json={"id": event_id, **body})
    except CalendarError as exc:
        if exc.status != 409:
            raise
        self._call("PATCH", calendar, f"/{quote(event_id, safe='')}", json=body)


GoogleCalendar.upsert_all_day = upsert_all_day


def authorized_session(credentials_path: str):
    """A requests session that signs every call as the service account. The imports are here on purpose."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(credentials_path, scopes=[SCOPE])
    return AuthorizedSession(credentials)
