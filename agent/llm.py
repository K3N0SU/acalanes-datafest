"""Provider clients. Both expose the same call:

    provider.research(system, prompt, trace) -> (text, sources)

Gemini: native Google Search grounding (the model searches by itself).
DeepSeek: function-calling loop over our own web_search / fetch_page tools.
"""
import json

from . import net, search
from .config import provider_settings

MAX_TOOL_ROUNDS = 8


class Provider:
    name = ""

    def __init__(self):
        s = provider_settings(self.name)
        if not s["key"]:
            raise RuntimeError(f"{self.name}: no API key set")
        self.key, self.model, self.effort = s["key"], s["model"], s["effort"]
        self.ledger = None  # optional budget.Ledger; set by the orchestrator

    def _check(self):
        if self.ledger is not None:
            self.ledger.check(self.name)

    def _spend(self, tokens):
        if self.ledger is not None:
            self.ledger.add(self.name, tokens)

    def research(self, system, prompt, trace=None):
        raise NotImplementedError

    def list_models(self):
        raise NotImplementedError


class Gemini(Provider):
    name = "gemini"
    base = "https://generativelanguage.googleapis.com/v1beta"

    def research(self, system, prompt, trace=None):
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.2,
                                 "thinkingConfig": {"thinkingLevel": self.effort}},
        }
        self._check()
        d = net.request_json(f"{self.base}/models/{self.model}:generateContent", body,
                             headers={"x-goog-api-key": self.key})
        self._spend(d.get("usageMetadata", {}).get("totalTokenCount", 0))
        cand = (d.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        meta = cand.get("groundingMetadata", {})
        sources = [{"title": c["web"].get("title", ""), "url": c["web"]["uri"]}
                   for c in meta.get("groundingChunks", []) if "web" in c]
        if trace is not None:
            trace.append({"provider": "gemini", "searches": meta.get("webSearchQueries", []),
                          "sources_returned": len(sources)})
        return text, sources

    def list_models(self):
        d = net.request_json(f"{self.base}/models?pageSize=200", headers={"x-goog-api-key": self.key})
        return [m["name"].split("/")[-1] for m in d.get("models", [])]


TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs and snippets. Use specific queries with dates and venue names.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_page",
        "description": "Download a public web page and return its text. Use to confirm a date and start time.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
]


class DeepSeek(Provider):
    name = "deepseek"
    base = "https://api.deepseek.com"

    def _chat(self, messages, tools=True):
        body = {"model": self.model, "messages": messages, "reasoning_effort": self.effort}
        if tools:
            body["tools"] = TOOLS
        self._check()
        d = net.request_json(f"{self.base}/chat/completions", body,
                             headers={"Authorization": f"Bearer {self.key}"}, timeout=600)
        self._spend(d.get("usage", {}).get("total_tokens", 0))
        return d

    def reason(self, system, prompt):
        """Pure reasoning, no tools. Returns the final answer text."""
        d = self._chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], tools=False)
        return d["choices"][0]["message"].get("content") or ""

    def research(self, system, prompt, trace=None):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        sources, seen = [], set()
        for _ in range(MAX_TOOL_ROUNDS):
            msg = self._chat(messages)["choices"][0]["message"]
            messages.append({k: v for k, v in msg.items() if v is not None})
            calls = msg.get("tool_calls") or []
            if not calls:
                return msg.get("content") or "", sources
            for c in calls:
                fn = c["function"]["name"]
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                if fn == "web_search":
                    results = search.web_search(args.get("query", ""))
                    out = search.format_results(results)
                    for r in results:
                        if r["url"] and r["url"] not in seen:
                            seen.add(r["url"])
                            sources.append({"title": r["title"], "url": r["url"]})
                elif fn == "fetch_page":
                    out = net.fetch_page_text(args.get("url", ""))
                else:
                    out = "unknown tool"
                if trace is not None:
                    trace.append({"provider": "deepseek", "tool": fn, "args": args})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        # out of rounds: force a final answer without tools
        messages.append({"role": "user", "content": "Stop searching. Give your final answer now."})
        return self._chat(messages, tools=False)["choices"][0]["message"].get("content") or "", sources

    def list_models(self):
        d = net.request_json(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"})
        return [m["id"] for m in d.get("data", [])]


CLASSES = {"gemini": Gemini, "deepseek": DeepSeek}


def get_provider(name: str) -> Provider:
    return CLASSES[name]()
