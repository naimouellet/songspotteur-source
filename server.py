"""Local development server for Songspotteur: serves public/ with no caching.

Usage: python3 server.py [port]
"""
import http.server
import pathlib
import re
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent / "public"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        # Serve the page with each asset link stamped with that file's
        # modification time, so an edited file always gets a URL the browser
        # has never cached.
        if urllib.parse.urlparse(self.path).path not in ("/", "/index.html"):
            return super().do_GET()
        html = (ROOT / "index.html").read_text()
        html = re.sub(r'(href|src)="([\w.-]+\.(?:css|js))(?:\?v=\d+)?"',
                      lambda m: f'{m[1]}="{m[2]}?v={int((ROOT / m[2]).stat().st_mtime)}"', html)
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # The game changes often during development: never let the browser
        # mix a fresh page with a stale stylesheet or script.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
