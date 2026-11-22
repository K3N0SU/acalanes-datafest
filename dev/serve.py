"""Local server for the site. Serves the page exactly as it will deploy, nothing else.

  /usr/local/bin/python3 dev/serve.py          # then open http://127.0.0.1:5180
  /usr/local/bin/python3 dev/serve.py 8080     # another port

Only listens on 127.0.0.1 and only serves the site's own folders, never .env or the rest of the repo.
"""
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5180

# URL prefix -> folder. Mirrors the deployed layout (public/ at the root), so paths work the same deployed.
ROUTES = {
    "/src/": ROOT / "src",
    "/data/": ROOT / "public" / "data",
    "/geo/": ROOT / "public" / "geo",
    "/config/": ROOT / "public" / "config",
    "/assets/": ROOT / "public" / "assets",
}
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".svg": "image/svg+xml", ".woff2": "font/woff2", ".html": "text/html; charset=utf-8",
         ".webp": "image/webp", ".avif": "image/avif", ".mp4": "video/mp4", ".webm": "video/webm"}


def resolve(path: str):
    if path in ("/", "/index.html"):
        return ROOT / "index.html"
    for prefix, base in ROUTES.items():
        if path.startswith(prefix):
            rel = path[len(prefix):]
            if any(part.startswith(".") for part in rel.split("/")):
                return None
            target = (base / rel).resolve()
            if base.resolve() in target.parents and target.is_file():
                return target
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        f = resolve(unquote(urlsplit(self.path).path))
        if f is None:
            return self._send(404, b"Not found", "text/plain")
        ctype = TYPES.get(f.suffix.lower()) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        self._send(200, f.read_bytes(), ctype)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Site running at http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
