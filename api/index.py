import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote


ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"


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

    def _serve_docs_file(self, requested_path: str):
        path = requested_path or "/"
        if path == "/":
            target = DOCS_DIR / "index.html"
        else:
            relative = Path(unquote(path.lstrip("/")))
            target = (DOCS_DIR / relative).resolve()

            if DOCS_DIR not in target.parents and target != DOCS_DIR:
                self._send_json({"ok": False, "error": "Invalid path."}, status=HTTPStatus.BAD_REQUEST)
                return

        if not target.exists() or not target.is_file():
            self._send_json(
                {
                    "ok": False,
                    "error": "This Vercel deployment is read-only. Run locally to add or index books."
                },
                status=HTTPStatus.NOT_FOUND,
            )
            return

        content_type, _ = mimetypes.guess_type(str(target))
        self._send_bytes(target.read_bytes(), content_type or "application/octet-stream")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json({"ok": False, "mode": "shared-app"})
            return

        if path.startswith("/api/"):
            self._send_json(
                {
                    "ok": False,
                    "error": "This Vercel deployment is read-only. Run locally to add or index books."
                },
                status=HTTPStatus.NOT_FOUND,
            )
            return

        self._serve_docs_file(path)

    def do_POST(self):
        self._send_json(
            {
                "ok": False,
                "error": "Uploads are disabled on the shared Vercel deployment. Run locally to add books."
            },
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
