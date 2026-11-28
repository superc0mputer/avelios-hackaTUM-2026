"""The website as the desktop app shows it: during the interview, on top of the live patient.

Serves teacher-ui/ unchanged and adds, only here, hud.css and hud.js from this folder (the see-through
interview with the patient video behind it, the API key screen). The website itself needs no changes for
this, and `python teacher-ui/server.py` looks exactly as before. See README.md in this folder.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HUD_ROOT = Path(__file__).resolve().parent
# repo: app/hud/page_server.py -> teacher-ui/ ; packaged app: app/hud/page_server.py -> app/teacher-ui/
SITE = next(
    folder for folder in (HUD_ROOT.parent / "teacher-ui", HUD_ROOT.parents[1] / "teacher-ui")
    if (folder / "server.py").is_file()
)
sys.path.insert(0, str(SITE))
import server as site  # noqa: E402 - the website's own server

HUD_FILES = {"hud.css": "text/css", "hud.js": "text/javascript"}
# Key management lives in the voice server; the page reaches it through these
PROXY_ROUTES = {"/api/keys": "/keys", "/api/signed-url": "/signed-url"}
HEAD_TAGS = '<link rel="stylesheet" href="/hud/hud.css">\n    <script src="/hud/hud.js"></script>\n  '


def add_hud(html: str) -> str:
    """Load the HUD after the website's own stylesheet, so its rules win."""
    return html.replace("<html", '<html class="vip-hud"', 1).replace("</head>", HEAD_TAGS + "</head>", 1)


class HudHandler(site.TeacherHandler):
    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")  # after an update, show the new page
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            page = add_hud((site.STATIC_ROOT / "index.html").read_text(encoding="utf-8"))
            self._send(page.encode("utf-8"), "text/html")
        elif path.startswith("/hud/") and path[5:] in HUD_FILES:
            self._send((HUD_ROOT / path[5:]).read_bytes(), HUD_FILES[path[5:]])
        elif path in PROXY_ROUTES:
            self._proxy("GET", PROXY_ROUTES[path])
        else:
            super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == "/api/keys":
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= site.MAX_REQUEST_BYTES:
                self._json(413, {"error": "The request is too large."})
                return
            self._proxy("POST", "/keys", self.rfile.read(length))
        else:
            super().do_POST()

    def do_DELETE(self):
        if urlparse(self.path).path == "/api/keys":
            self._proxy("DELETE", "/keys")
        else:
            self.send_error(404, "Unknown API route")

    def _send(self, data: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self, method: str, path: str, body: bytes | None = None):
        """Pass a key request to the voice server. Only from this computer, and only from this page."""
        origin = self.headers.get("Origin")
        local_names = {f"127.0.0.1:{site.PORT}", f"localhost:{site.PORT}"}
        # Host and Origin checks keep other websites in a browser away from the key routes
        if (self.client_address[0] not in ("127.0.0.1", "::1") or self.headers.get("Host") not in local_names
                or (origin and urlparse(origin).netloc not in local_names)):
            self._json(403, {"error": "Keys can only be managed on this computer."})
            return
        request = urllib.request.Request(
            f"{site.VOICE_SERVER_URL}{path}", data=body, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status, data = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, data = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            self._json(502, {"error": f"The voice server is not running at {site.VOICE_SERVER_URL}."})
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    server = ThreadingHTTPServer((site.HOST, site.PORT), HudHandler)
    print(f"VIP app page: http://{site.HOST}:{site.PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
