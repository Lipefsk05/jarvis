import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.gcal import CalendarError, GoogleCalendar, event_from_api, new_event_id

TZ = ZoneInfo("America/Sao_Paulo")
START = datetime(2026, 10, 17, 15, 0, tzinfo=TZ)


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body
        self.content = b"x" if body is not None else b""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses, error=None):
        self.responses, self.calls, self.error = list(responses), [], error

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0)


def api_event(**extra):
    return {"id": "e1", "summary": "Reunião", "start": {"dateTime": "2026-10-17T18:00:00Z"},
            "end": {"dateTime": "2026-10-17T19:00:00Z"}, **extra}


class ParseTest(unittest.TestCase):
    def test_timed_event_is_converted_to_the_local_zone(self):
        event = event_from_api(api_event(location=" Sala 2 "), "a@x.com", TZ)
        self.assertEqual((event.title, event.start.hour, event.location, event.all_day), ("Reunião", 15, "Sala 2", False))

    def test_all_day_event(self):
        raw = {"id": "e2", "summary": "Feriado", "start": {"date": "2026-10-17"}, "end": {"date": "2026-10-18"}}
        event = event_from_api(raw, "a@x.com", TZ)
        self.assertTrue(event.all_day)
        self.assertEqual((event.start.hour, event.end.day), (0, 18))

    def test_cancelled_or_broken_items_are_dropped_and_untitled_ones_named(self):
        self.assertIsNone(event_from_api(api_event(status="cancelled"), "a", TZ))
        self.assertIsNone(event_from_api({"id": "x"}, "a", TZ))
        self.assertEqual(event_from_api({**api_event(), "summary": None}, "a", TZ).title, "(sem título)")

    def test_new_ids_are_valid_and_unique(self):
        first, second = new_event_id(), new_event_id()
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[a-v0-9]{5,}$")  # Google accepts a-v and 0-9 only


class ClientTest(unittest.TestCase):
    def test_list_asks_for_expanded_recurrences_in_order(self):
        session = FakeSession(FakeResponse(200, {"items": [api_event(), {"id": "bad"}]}))
        events = GoogleCalendar(session, TZ).list_events("admin@cafelabs.net", START, START + timedelta(days=1))
        self.assertEqual(len(events), 1)
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertIn("/calendars/admin%40cafelabs.net/events", url)
        self.assertEqual((kwargs["params"]["singleEvents"], kwargs["params"]["orderBy"]), ("true", "startTime"))

    def test_insert_sends_our_id_title_and_times_and_no_attendees(self):
        session = FakeSession(FakeResponse(200, api_event()))
        GoogleCalendar(session, TZ).insert("a@x.com", "Reunião", START, START + timedelta(hours=1), "Sala 2", "jvabc")
        body = session.calls[0][2]["json"]
        self.assertEqual((body["id"], body["summary"], body["location"]), ("jvabc", "Reunião", "Sala 2"))
        self.assertEqual(body["start"]["timeZone"], "America/Sao_Paulo")
        self.assertNotIn("attendees", body)

    def test_move_patches_only_the_times(self):
        session = FakeSession(FakeResponse(200, api_event()))
        GoogleCalendar(session, TZ).move("a@x.com", "e1", START, START + timedelta(hours=1))
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "PATCH")
        self.assertTrue(url.endswith("/events/e1"))
        self.assertEqual(set(kwargs["json"]), {"start", "end"})

    def test_delete_succeeds_and_an_already_gone_event_counts_as_done(self):
        for status in (204, 404, 410):
            GoogleCalendar(FakeSession(FakeResponse(status)), TZ).delete("a@x.com", "e1")

    def test_errors_carry_the_status_and_never_the_library_exception(self):
        with self.assertRaises(CalendarError) as caught:
            GoogleCalendar(FakeSession(FakeResponse(403, {})), TZ).list_events("a@x.com", START, START)
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(CalendarError) as caught:
            GoogleCalendar(FakeSession(error=ConnectionError("boom")), TZ).list_events("a@x.com", START, START)
        self.assertEqual(caught.exception.status, 0)
        self.assertNotIn("boom", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class AllDayTest(unittest.TestCase):
    def test_upsert_creates_a_transparent_all_day_item_with_our_id(self):
        from datetime import date
        session = FakeSession(FakeResponse(200, {"id": "jvt1"}))
        GoogleCalendar(session, TZ).upsert_all_day("t@group.calendar.google.com", "jvt1", "Landing", date(2026, 10, 17), "empresa/dindin")
        body = session.calls[0][2]["json"]
        self.assertEqual((body["id"], body["summary"], body["transparency"]), ("jvt1", "Landing", "transparent"))
        self.assertEqual((body["start"], body["end"]), ({"date": "2026-10-17"}, {"date": "2026-10-18"}))

    def test_an_id_that_is_already_taken_is_patched_instead(self):
        from datetime import date
        session = FakeSession(FakeResponse(409, {}), FakeResponse(200, {"id": "jvt1"}))
        GoogleCalendar(session, TZ).upsert_all_day("t@x", "jvt1", "Landing", date(2026, 10, 17))
        self.assertEqual([c[0] for c in session.calls], ["POST", "PATCH"])
        self.assertEqual(session.calls[1][2]["json"]["status"], "confirmed")  # a deleted item comes back

    def test_other_errors_are_not_hidden(self):
        from datetime import date
        with self.assertRaises(CalendarError):
            GoogleCalendar(FakeSession(FakeResponse(403, {})), TZ).upsert_all_day("t@x", "jvt1", "x", date(2026, 10, 17))
