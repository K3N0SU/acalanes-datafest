"""Offline tests for the Claude orchestrator and budgets. A fake Anthropic client replays scripted turns."""
import unittest
from datetime import date
from types import SimpleNamespace as NS
from unittest import mock

from agent import orchestrator
from agent.budget import BudgetExceeded, Ledger

VENUES = [{"venue": "Oracle Park", "capacity_n": 41000, "capacity": "41000", "nearest_station": "Embarcadero"}]
EVENT = {"name": "Show", "venue": "Oracle Park", "date": "2026-11-25", "start_time": "19:00",
         "expected_attendance": 99999, "category": "concert", "notes": "",
         "source_urls": ["https://a.com/1", "https://b.com/2"]}


def usage(inp=1000, out=200):
    return NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def tool(name, inp, id_="t1"):
    return NS(type="tool_use", name=name, input=inp, id=id_)


def msg(blocks, stop="tool_use", u=None):
    return NS(content=blocks, stop_reason=stop, usage=u or usage(), stop_details=None)


class FakeClient:
    def __init__(self, turns):
        self.turns, self.requests = list(turns), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})  # snapshot; the loop keeps appending
        return self.turns.pop(0)


class FakeGemini:
    name = "gemini"
    ledger = None

    def research(self, system, prompt, trace=None):
        self.ledger.check("gemini")
        self.ledger.add("gemini", 5000)
        return "Concert Nov 25 7pm", [{"title": "venue", "url": "https://a.com/1"}]


class Ledgers(unittest.TestCase):
    def test_caps_and_unlimited(self):
        l = Ledger({"claude": 100, "gemini": 50})
        l.add("deepseek", 10 ** 9)
        l.check("deepseek")                       # never raises
        l.add("gemini", 50)
        with self.assertRaises(BudgetExceeded):
            l.check("gemini")
        self.assertIn("unlimited", l.status())

    def test_env_overrides(self):
        with mock.patch.dict("os.environ", {"CLAUDE_TOKEN_BUDGET": "50000", "GEMINI_TOKEN_BUDGET": "25000"}):
            l = Ledger()
        self.assertEqual((l.limits["claude"], l.limits["gemini"], l.limits["deepseek"]), (50000, 25000, None))


class Orchestrator(unittest.TestCase):
    def test_search_then_submit(self):
        client = FakeClient([
            msg([tool("gemini_search", {"question": "Oracle Park events"})]),
            msg([tool("submit_events", {"events": [EVENT]}, "t2")]),
        ])
        out = orchestrator.run(date(2026, 11, 23), VENUES, gemini=FakeGemini(), ledger=Ledger(),
                               client=client, log=lambda *_: None)
        self.assertEqual(out["counts"]["accepted"], 1)
        self.assertEqual(out["accepted"][0]["expected_attendance"], 41000)      # harness capped it
        self.assertEqual(out["budget"]["gemini"]["used"], 5000)
        self.assertEqual(out["budget"]["claude"]["used"], 2400)
        req = client.requests[1]
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["fallbacks"], "default")
        last_user = req["messages"][-1]["content"]
        self.assertEqual(last_user[0]["type"], "tool_result")
        self.assertIn("[token budget]", last_user[-1]["text"])                  # budget exposed to Claude

    def test_gemini_budget_exhaustion_reported_to_claude(self):
        client = FakeClient([
            msg([tool("gemini_search", {"question": "q"})]),
            msg([tool("submit_events", {"events": []}, "t2")]),
        ])
        out = orchestrator.run(date(2026, 11, 23), VENUES, gemini=FakeGemini(),
                               ledger=Ledger({"gemini": 0}), client=client, log=lambda *_: None)
        result = client.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("budget exhausted", result["content"])
        self.assertTrue(out["submitted"])

    def test_claude_budget_forces_finalize(self):
        client = FakeClient([
            msg([tool("gemini_search", {"question": "q"})], u=usage(30000, 1000)),
            msg([tool("submit_events", {"events": [EVENT]}, "t2")]),
        ])
        out = orchestrator.run(date(2026, 11, 23), VENUES, gemini=FakeGemini(),
                               ledger=Ledger({"claude": 50000}), client=client, log=lambda *_: None)
        texts = [b["text"] for b in client.requests[1]["messages"][-1]["content"] if b.get("type") == "text"]
        self.assertTrue(any("submit_events now" in t for t in texts))
        self.assertEqual(out["counts"]["accepted"], 1)

    def test_single_source_is_flagged(self):
        ev = dict(EVENT, source_urls=["https://a.com/1"])
        client = FakeClient([msg([tool("submit_events", {"events": [ev]})])])
        out = orchestrator.run(date(2026, 11, 23), VENUES, ledger=Ledger(), client=client, log=lambda *_: None)
        self.assertEqual(out["counts"]["flagged"], 1)


class DeepSeekLayers(unittest.TestCase):
    def test_three_passes(self):
        calls = []
        ds = NS(reason=lambda s, p: calls.append(p) or f"answer{len(calls)}")
        self.assertEqual(orchestrator.deepseek_multipass(ds, "t", "m", 3), "answer3")
        self.assertIn("Critique", calls[2])


if __name__ == "__main__":
    unittest.main()
