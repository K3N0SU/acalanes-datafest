"""Web search backends. DeepSeek has no built-in search, so it calls these as tools.
Gemini uses Google Search grounding natively and does not need them.

Pick with SEARCH_BACKEND = tavily | brave | duckduckgo (default: first key found, else duckduckgo).
"""
import os
import re
import urllib.parse
import urllib.request

from . import net


def _tavily(query, n):
    d = net.request_json("https://api.tavily.com/search",
                         {"query": query, "max_results": n, "search_depth": "advanced", "days": 30},
                         headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"})
    return [{"title": r.get("title", ""), "url": r["url"], "snippet": r.get("content", "")[:500]}
            for r in d.get("results", [])]


def _brave(query, n):
    q = urllib.parse.urlencode({"q": query, "count": n, "freshness": "pm"})
    d = net.request_json(f"https://api.search.brave.com/res/v1/web/search?{q}",
                         headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"]})
    return [{"title": r.get("title", ""), "url": r["url"], "snippet": re.sub("<[^>]+>", "", r.get("description", ""))[:500]}
            for r in d.get("web", {}).get("results", [])]


def _duckduckgo(query, n):
    """Keyless fallback: scrapes DuckDuckGo's HTML endpoint. Fragile; fine for a hackathon."""
    req = urllib.request.Request("https://html.duckduckgo.com/html/",
                                 data=urllib.parse.urlencode({"q": query}).encode(),
                                 headers={"User-Agent": net.UA})
    with net.urlopen(req) as r:
        html = r.read().decode("utf-8", "replace")
    if "result__a" not in html:
        raise RuntimeError("DuckDuckGo blocked the automated search. Set TAVILY_API_KEY or BRAVE_API_KEY (free tiers exist).")
    out = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S):
        href = m.group(1)
        if "uddg=" in href:
            href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
        strip = lambda s: re.sub(r"\s+", " ", re.sub("<[^>]+>", "", s)).strip()
        out.append({"title": strip(m.group(2)), "url": href, "snippet": strip(m.group(3))[:500]})
        if len(out) >= n:
            break
    return out


def backend_name() -> str:
    want = os.environ.get("SEARCH_BACKEND", "").lower()
    if want in ("tavily", "brave", "duckduckgo"):
        return want
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    if os.environ.get("BRAVE_API_KEY"):
        return "brave"
    return "duckduckgo"


def web_search(query: str, n: int = 8) -> list[dict]:
    fn = {"tavily": _tavily, "brave": _brave, "duckduckgo": _duckduckgo}[backend_name()]
    try:
        return fn(query, n)
    except Exception as e:
        return [{"title": "search error", "url": "", "snippet": str(e)[:300]}]


def format_results(results: list[dict]) -> str:
    return "\n".join(f"- {r['title']} | {r['url']}\n  {r['snippet']}" for r in results) or "no results"
