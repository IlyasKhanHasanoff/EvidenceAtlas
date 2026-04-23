import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from evidence_engine import answer_question


class handler(BaseHTTPRequestHandler):
    def _send_bytes(self, data: bytes, content_type: str, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status=status)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json({"ok": False, "mode": "shared-app"})
            return

        self._send_json({"ok": False, "error": "Route not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/answer":
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                payload = {}

            query = (payload.get("query") or "").strip()
            if not query:
                self._send_json({"error": "Enter a prompt first."}, status=HTTPStatus.BAD_REQUEST)
                return

            self._send_json(
                answer_question(
                    query,
                    topic=(payload.get("topic") or "").strip(),
                    subject=(payload.get("subject") or "").strip(),
                    source_id=(payload.get("sourceId") or "").strip(),
                )
            )
            return

        self._send_json(
            {
                "ok": False,
                "error": "Uploads are disabled on the shared Vercel deployment. Run locally to add books."
            },
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
