"""Offline tests: no network, no keys. Run from the repo root:  python -m unittest discover -s agent/tests -t ."""
import json
import unittest
from datetime import date
from unittest import mock

from agent import llm, net, pipeline

START, END = date(2026, 11, 23), date(2026, 11, 29)
VENUES = [
    {"venue": "Oracle Park", "capacity_n": 41000, "nearest_station": "Embarcadero"},
    {"venue": "Chase Center", "capacity_n": 18064, "nearest_station": "Powell"},
]


def ev(**kw):
    base = {"name": "Show", "venue": "Oracle Park", "date": "2026-11-25", "start_time": "19:05",
            "expected_attendance": 30000, "category": "sports", "source_urls": ["https://example.com/a"]}
    return {**base, **kw}


class Harness(unittest.TestCase):
    def test_confirmed_event_accepted(self):
        s, _, _ = pipeline.validate(ev(), VENUES, START, END, {"verdict": "confirmed"})
        self.assertEqual(s, "accepted")

    def test_unknown_venue_rejected(self):
        s, r, _ = pipeline.validate(ev(venue="Mystery Barn"), VENUES, START, END, {"verdict": "confirmed"})
        self.assertEqual(s, "rejected")
        self.assertIn("not in venue table", r[0])

    def test_date_outside_week_rejected(self):
        self.assertEqual(pipeline.validate(ev(date="2026-12-05"), VENUES, START, END, {"verdict": "confirmed"})[0], "rejected")

    def test_missing_source_rejected(self):
        self.assertEqual(pipeline.validate(ev(source_urls=[]), VENUES, START, END, {"verdict": "confirmed"})[0], "rejected")

    def test_bad_time_rejected(self):
        self.assertEqual(pipeline.validate(ev(start_time="evening"), VENUES, START, END, {"verdict": "confirmed"})[0], "rejected")

    def test_attendance_capped(self):
        _, r, e = pipeline.validate(ev(expected_attendance=99999), VENUES, START, END, {"verdict": "confirmed"})
        self.assertEqual(e["expected_attendance"], 41000)
        self.assertTrue(any("capped" in x for x in r))

    def test_disputed_rejected_unconfirmed_flagged(self):
        self.assertEqual(pipeline.validate(ev(), VENUES, START, END, {"verdict": "disputed"})[0], "rejected")
        self.assertEqual(pipeline.validate(ev(), VENUES, START, END, {"verdict": "not_found"})[0], "flagged")
        self.assertEqual(pipeline.validate(ev(), VENUES, START, END, None)[0], "flagged")

    def test_official_skips_checker(self):
        self.assertEqual(pipeline.validate(ev(official=True), VENUES, START, END)[0], "accepted")

    def test_disruption_needs_no_venue(self):
        s, _, e = pipeline.validate(ev(category="disruption", venue="Transbay Tube", start_time=None),
                                    VENUES, START, END, {"verdict": "confirmed"})
        self.assertEqual((s, e["kind"]), ("accepted", "advisory"))

    def test_dedupe_merges_sources(self):
        out = pipeline.dedupe([ev(source_urls=["https://a.com"]), ev(source_urls=["https://b.com"])])
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["source_urls"]), 2)

    def test_extract_json(self):
        self.assertEqual(pipeline.extract_json('Here:\n```json\n[{"a": 1}]\n```'), [{"a": 1}])
        self.assertEqual(pipeline.extract_json('{"verdict": "confirmed"}'), {"verdict": "confirmed"})
        self.assertIsNone(pipeline.extract_json("no json here"))


class Fake:
    def __init__(self, name, reply):
        self.name, self.reply = name, reply

    def research(self, system, prompt, trace=None):
        return self.reply(system, prompt), []


class EndToEnd(unittest.TestCase):
    def test_full_run_with_fakes(self):
        found = [ev(), ev(name="Fake gig", venue="Chase Center", source_urls=["https://x.com/1"]),
                 ev(name="Wrong day", date="2027-01-01")]
        finder = Fake("finder", lambda s, p: json.dumps(found))
        checker = Fake("checker", lambda s, p: json.dumps(
            {"verdict": "disputed" if "Fake gig" in p else "confirmed"}))
        with mock.patch("agent.sources.mlb_home_games", return_value=[]):
            out = pipeline.run(START, [finder, checker], VENUES)
        self.assertEqual(out["counts"], {"accepted": 1, "flagged": 0, "rejected": 2})
        self.assertEqual(out["checker"], "checker")


class Safety(unittest.TestCase):
    def test_blocks_private_and_non_http(self):
        for u in ("http://127.0.0.1/x", "http://localhost/", "file:///etc/passwd", "ftp://a.com", "http://169.254.169.254/"):
            self.assertFalse(net.is_public_http_url(u), u)


class DeepSeekLoop(unittest.TestCase):
    def test_tool_loop_then_answer(self):
        with mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": "k"}):
            p = llm.DeepSeek()
        replies = iter([
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "q"}'}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "[]"}}]},
        ])
        with mock.patch.object(p, "_chat", side_effect=lambda *a, **k: next(replies)), \
                mock.patch("agent.search.web_search", return_value=[{"title": "t", "url": "https://e.com", "snippet": "s"}]):
            text, srcs = p.research("sys", "go", [])
        self.assertEqual((text, srcs[0]["url"]), ("[]", "https://e.com"))
        self.assertEqual(p.effort, "high")


if __name__ == "__main__":
    unittest.main()
