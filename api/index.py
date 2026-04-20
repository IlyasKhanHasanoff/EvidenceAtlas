import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/health"):
            self._send_json({"ok": False, "mode": "shared-app"})
            return

        self._send_json(
            {
                "ok": False,
                "error": "This Vercel deployment is read-only. Run locally to add or index books."
            },
            status=HTTPStatus.NOT_FOUND,
        )

    def do_POST(self):
        self._send_json(
            {
                "ok": False,
                "error": "Uploads are disabled on the shared Vercel deployment. Run locally to add books."
            },
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
