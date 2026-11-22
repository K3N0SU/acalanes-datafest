"""Tiny stdlib HTTP helpers with retries, plus a safe page fetcher."""
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; Rushcast/1.0; student-project)"


def _ssl_context():
    """python.org builds on macOS ship without CA certs; fall back to certifi or the system bundle."""
    import os
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for cafile in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem"):
        if os.path.exists(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


_CTX = _ssl_context()


def urlopen(req, timeout=30):
    return urllib.request.urlopen(req, timeout=timeout, context=_CTX)


def request_json(url, body=None, headers=None, method=None, timeout=90, retries=3):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json", "User-Agent": UA, **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method or ("POST" if data else "GET"))
    last = None
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            last = RuntimeError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}: {detail}")
            if e.code not in (429, 500, 502, 503, 504):
                raise last
        except (urllib.error.URLError, TimeoutError) as e:
            last = RuntimeError(f"network error: {e}")
        time.sleep(2 ** attempt)
    raise last


def is_public_http_url(url: str) -> bool:
    """Block non-http(s) schemes and private/loopback hosts (search results are untrusted input)."""
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except socket.gaierror:
        return False
    return True


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def fetch_page_text(url: str, max_chars: int = 8000) -> str:
    if not is_public_http_url(url):
        return "ERROR: URL not allowed (must be a public http/https address)."
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urlopen(req) as r:
            if not is_public_http_url(r.geturl()):
                return "ERROR: redirected to a disallowed address."
            raw = r.read(1_500_000).decode("utf-8", "replace")
    except Exception as e:  # return as text so the model can move on
        return f"ERROR: could not fetch ({e})"
    parser = _Text()
    parser.feed(raw)
    return re.sub(r"\s+", " ", " ".join(parser.parts))[:max_chars]
