"""Local server for Songspotteur: serves public/ and opens songs in the Music app.

Browsers (and the Claude browser pane) often block music:// links, so the page
asks this server to run macOS `open` on the Apple Music link instead.

Usage: python3 server.py [port]
"""
import http.server
import pathlib
import re
import subprocess
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent / "public"
ALLOWED = "music://music.apple.com/"


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

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/open-in-music":
            return self.send_error(404)
        url = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        if not url.startswith(ALLOWED):
            return self.send_error(400, "Lien Apple Music attendu")
        subprocess.run(["open", url], check=False)
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
    # Local only: this endpoint launches apps on this Mac.
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
