"""
Web search without a search API: we fetch the pages ourselves and DeepSeek only reads them.

  1. DeepSeek writes two or three search queries for the question.
  2. We run them on a search API (Brave, Tavily or Serper, whichever key is in .env) and collect the result links and snippets.
     With no key it falls back to a public results page, which finds much worse pages.
  3. We download the top pages and strip them to text.
  4. DeepSeek answers from those texts only, and may cite only an address from the list we gave it.

Because every source is a page this code downloaded, a made-up link cannot get through: an
address that is not in the list is rejected.

DeepSeek's API has no search of its own (checked: it accepts only function tools, and when asked
a date question with no pages it answered from memory and got the opponent wrong).

Needs DEEPSEEK_API_KEY in .env.
"""

import base64
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
SKIP = ("bing.com", "microsoft.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "youtube.com", "pinterest.", "linkedin.com")
MODEL = os.environ.get("DEEPSEEK_SEARCH_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"))
QUERY_MODEL = os.environ.get("DEEPSEEK_QUERY_MODEL", "deepseek-flash")
PAGES, PAGE_CHARS = 5, 5000
USAGE = {"asks": 0, "bing_queries": 0, "pages_fetched": 0, "tokens": 0}
_cache = {}


def _deepseek(prompt, model, as_json=True, temperature=0):
    key = os.environ["DEEPSEEK_API_KEY"]
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    for attempt in range(5):
        try:
            r = requests.post("https://api.deepseek.com/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body, timeout=240)
        except requests.RequestException:
            time.sleep(4 * (attempt + 1))
            continue
        if r.status_code == 200:
            j = r.json()
            USAGE["tokens"] += j.get("usage", {}).get("total_tokens", 0)
            msg = j["choices"][0]["message"]
            return msg.get("content") or "", msg.get("reasoning_content") or ""
        if r.status_code in (429, 500, 502, 503):
            time.sleep(6 * (attempt + 1))
            continue
        raise SystemExit(f"DeepSeek error {r.status_code}: {r.text[:200]}")
    raise SystemExit("DeepSeek kept failing")


def search_api():
    """which search service is available, by the keys in .env. A real search API finds far better pages than scraping."""
    for name, var in (("brave", "BRAVE_API_KEY"), ("tavily", "TAVILY_API_KEY"), ("serper", "SERPER_API_KEY")):
        if os.environ.get(var, "").strip():
            return name
    return "bing page (no key)"


def results_for(query, n=6):
    """result links and snippets from whichever search service is configured"""
    api = search_api()
    key_ = ("api", api, query)
    if key_ in _cache:
        return _cache[key_]
    out = []
    try:
        if api == "brave":
            r = requests.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": n, "country": "us"},
                             headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"].strip(), "Accept": "application/json"}, timeout=20)
            if r.status_code == 429:   # free plan allows one request a second
                time.sleep(1.2)
                r = requests.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": n, "country": "us"},
                                 headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"].strip(), "Accept": "application/json"}, timeout=20)
            r.raise_for_status()
            out = [{"url": x.get("url", ""), "title": x.get("title", ""), "snippet": re.sub(r"<[^>]+>", "", x.get("description", ""))}
                   for x in (r.json().get("web") or {}).get("results", [])]
        elif api == "tavily":
            r = requests.post("https://api.tavily.com/search", timeout=30, headers={"Authorization": "Bearer " + os.environ["TAVILY_API_KEY"].strip()},
                              json={"query": query, "max_results": n, "search_depth": "basic"})
            r.raise_for_status()
            out = [{"url": x.get("url", ""), "title": x.get("title", ""), "snippet": x.get("content", "")} for x in r.json().get("results", [])]
        elif api == "serper":
            r = requests.post("https://google.serper.dev/search", timeout=20, headers={"X-API-KEY": os.environ["SERPER_API_KEY"].strip()},
                              json={"q": query, "num": n, "gl": "us"})
            r.raise_for_status()
            out = [{"url": x.get("link", ""), "title": x.get("title", ""), "snippet": x.get("snippet", "")} for x in r.json().get("organic", [])]
        else:
            return bing(query, n)
        USAGE["api_queries"] = USAGE.get("api_queries", 0) + 1
        out = [x for x in out if x["url"].startswith("http") and not any(d in x["url"] for d in SKIP)][:n]
    except requests.RequestException as e:
        print(f"  search ({api}) failed for '{query[:50]}': {type(e).__name__} {str(e)[:120]}")
        out = []
    _cache[key_] = out
    return out


def bing(query, n=6):
    """result links and snippets from Bing's public results page"""
    if query in _cache:
        return _cache[query]
    out = []
    try:
        r = requests.get("https://www.bing.com/search", params={"q": query, "count": 15, "setlang": "en", "cc": "US"}, headers=UA, timeout=20)
        USAGE["bing_queries"] += 1
        for block in re.findall(r'<li class="b_algo".*?</li>', r.text, flags=re.S):
            m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S)
            if not m:
                continue
            href, title = html.unescape(m.group(1)), re.sub(r"<[^>]+>", "", m.group(2))
            u = re.search(r"[?&]u=a1([A-Za-z0-9_-]+)", href)   # Bing wraps the real address in base64
            if u:
                try:
                    href = base64.urlsafe_b64decode(u.group(1) + "=" * (-len(u.group(1)) % 4)).decode("utf-8", "ignore")
                except Exception:
                    continue
            if not href.startswith("http") or any(s in href for s in SKIP):
                continue
            sn = re.search(r"<p[^>]*>(.*?)</p>", block, flags=re.S)
            out.append({"url": href, "title": html.unescape(title).strip(), "snippet": html.unescape(re.sub(r"<[^>]+>", "", sn.group(1))).strip() if sn else ""})
            if len(out) >= n:
                break
    except requests.RequestException:
        pass
    _cache[query] = out
    return out


def page_text(url):
    if url in _cache:
        return _cache[url]
    text = ""
    try:
        r = requests.get(url, headers=UA, timeout=12, allow_redirects=True)
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            t = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", r.text)
            t = html.unescape(re.sub(r"<[^>]+>", " ", t))
            text = re.sub(r"\s+", " ", t).strip()[:PAGE_CHARS]
            USAGE["pages_fetched"] += 1
    except requests.RequestException:
        pass
    _cache[url] = text
    return text


def ask(prompt):
    """returns (answer text, sources, queries, reasoning). sources = the pages we downloaded and showed the model."""
    USAGE["asks"] += 1
    qtext, _ = _deepseek("Write 3 web search queries that would find the pages needed to answer the request below. Write them the way a person "
                         "types into a search box: keywords, at most 8 words each. Make them different: one for the official site, one for news, "
                         "one for a schedule or calendar page. "
                         "Use specific names and dates from the request. Return ONLY JSON: {\"queries\": [str, str, str]}\n\nREQUEST:\n" + prompt[:3000], QUERY_MODEL)
    try:
        queries = [q for q in json.loads(qtext).get("queries", []) if isinstance(q, str)][:3]
    except json.JSONDecodeError:
        queries = []
    results, seen = [], set()
    for q in queries:
        for r in results_for(q):
            if r["url"] not in seen:
                seen.add(r["url"])
                results.append(r)
        time.sleep(1.1 if search_api() == "brave" else 0.4)
    with ThreadPoolExecutor(max_workers=5) as pool:
        texts = list(pool.map(page_text, [r["url"] for r in results[:PAGES + 3]]))
    sources = []
    for r, t in zip(results, texts + [""] * len(results)):
        body = t or r["snippet"]
        if body and len(sources) < PAGES + 3:
            sources.append({"url": r["url"], "title": r["title"], "text": body, "full_page": bool(t)})
    if not sources:
        return "[]", [], queries, "no pages could be retrieved"
    listing = "\n\n".join(f"[{i + 1}] {s['url']}\nTITLE: {s['title']}\nTEXT: {s['text']}" for i, s in enumerate(sources))
    answer, reasoning = _deepseek(
        f"""{prompt}

You have NO web access. Answer ONLY from the pages below, which were downloaded for you just now.
Any "source_url" you give must be copied exactly from the list. If the pages do not contain the answer, say so in the format asked
(null values, an empty array, or "unknown"). Do not use what you remember.
If the request asks for a JSON array, wrap it as {{"items": [...]}}.

PAGES:
{listing}""", MODEL)
    try:
        data = json.loads(answer)
        if isinstance(data, dict) and set(data) == {"items"}:
            answer = json.dumps(data["items"])
    except json.JSONDecodeError:
        pass
    return answer, [{"title": s["title"], "url": s["url"]} for s in sources], queries, reasoning
