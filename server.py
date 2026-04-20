import cgi
import json
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pypdf import PdfReader


ROOT = Path(__file__).parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = ROOT / "data"
UPLOADS_DIR = ROOT / "uploads"
DB_PATH = DATA_DIR / "evidence.sqlite"
SAMPLE_PATH = DATA_DIR / "books.json"

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is", "it",
    "of", "on", "or", "that", "the", "there", "this", "to", "was", "what", "when", "where",
    "which", "who", "why", "with"
}


def tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [token for token in cleaned.split() if token and token not in STOP_WORDS]


def unique(values):
    return sorted(set(values))


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def derive_keywords(text: str) -> list[str]:
    return unique(tokenize(text))[:12]


def split_into_excerpt_chunks(text: str) -> list[str]:
    cleaned = normalize_whitespace(text)
    if not cleaned:
      return []

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks = []
    current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= 420:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = sentence

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if len(chunk) >= 90]


def connect():
    return sqlite3.connect(DB_PATH)


def init_schema():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT UNIQUE,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                year TEXT NOT NULL,
                subject TEXT NOT NULL,
                original_filename TEXT,
                upload_path TEXT,
                ingestion_status TEXT NOT NULL,
                excerpt_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS excerpts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_ref TEXT NOT NULL,
                source_row_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                year TEXT NOT NULL,
                subject TEXT NOT NULL,
                page INTEGER NOT NULL,
                excerpt TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_row_id) REFERENCES sources(id)
            )
            """
        )
        conn.commit()


def source_count() -> int:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM sources").fetchone()
    return int(row[0])


def seed_database():
    if source_count():
        return

    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    grouped = defaultdict(list)

    for record in payload["records"]:
        key = (record["title"], record["author"], str(record["year"]), record["subject"])
        grouped[key].append(record)

    with connect() as conn:
        for (title, author, year, subject), records in grouped.items():
            source_id = "SEED-" + re.sub(r"[^A-Z0-9]+", "-", title.upper()).strip("-")
            cursor = conn.execute(
                """
                INSERT INTO sources (
                    source_id, title, author, year, subject, original_filename, upload_path,
                    ingestion_status, excerpt_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    title,
                    author,
                    year,
                    subject,
                    None,
                    None,
                    "seeded",
                    len(records),
                    datetime.utcnow().isoformat()
                )
            )
            source_row_id = cursor.lastrowid

            for record in records:
                conn.execute(
                    """
                    INSERT INTO excerpts (
                        source_ref, source_row_id, title, author, year, subject, page,
                        excerpt, keywords_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["sourceId"],
                        source_row_id,
                        title,
                        author,
                        year,
                        subject,
                        int(record["page"]),
                        record["excerpt"],
                        json.dumps(record.get("keywords", [])),
                        datetime.utcnow().isoformat()
                    )
                )
        conn.commit()


def get_stats():
    with connect() as conn:
        excerpt_count = conn.execute("SELECT COUNT(*) FROM excerpts").fetchone()[0]
        source_count_value = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        subject_count = conn.execute("SELECT COUNT(DISTINCT subject) FROM excerpts").fetchone()[0]
        pending_ocr_count = conn.execute(
            "SELECT COUNT(*) FROM sources WHERE ingestion_status = 'needs_ocr'"
        ).fetchone()[0]

    return {
        "excerptCount": int(excerpt_count),
        "sourceCount": int(source_count_value),
        "subjectCount": int(subject_count),
        "pendingOcrCount": int(pending_ocr_count),
    }


def get_subjects():
    with connect() as conn:
        rows = conn.execute("SELECT DISTINCT subject FROM excerpts ORDER BY subject ASC").fetchall()
    return [row[0] for row in rows]


def list_sources():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT source_id, title, author, year, subject, ingestion_status, excerpt_count, original_filename
            FROM sources
            ORDER BY id DESC
            """
        ).fetchall()

    return [
        {
            "sourceId": row[0],
            "title": row[1],
            "author": row[2],
            "year": row[3],
            "subject": row[4],
            "ingestionStatus": row[5],
            "excerptCount": row[6],
            "originalFilename": row[7],
        }
        for row in rows
    ]


def search(query: str, subject: str, min_terms: int):
    normalized_query = query.strip()
    if not normalized_query:
        return []

    query_tokens = unique(tokenize(normalized_query))

    with connect() as conn:
        if subject:
            rows = conn.execute(
                """
                SELECT source_ref, title, author, year, subject, page, excerpt, keywords_json
                FROM excerpts
                WHERE subject = ?
                """,
                (subject,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT source_ref, title, author, year, subject, page, excerpt, keywords_json
                FROM excerpts
                """
            ).fetchall()

    matches = []
    for row in rows:
        keywords = json.loads(row[7] or "[]")
        combined = set(tokenize(" ".join([row[1], row[2], row[4], row[6], *keywords])))
        matched_terms = [token for token in query_tokens if token in combined]
        if len(matched_terms) < min_terms:
            continue

        matches.append(
            {
                "sourceId": row[0],
                "title": row[1],
                "author": row[2],
                "year": row[3],
                "subject": row[4],
                "page": int(row[5]),
                "excerpt": row[6],
                "matches": matched_terms,
                "matchCount": len(matched_terms),
            }
        )

    return sorted(matches, key=lambda item: (-item["matchCount"], item["page"]))


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", name)


def ingest_pdf(file_path: Path, original_name: str, subject: str, author: str, year: str):
    reader = PdfReader(str(file_path))
    title = re.sub(r"\.pdf$", "", original_name, flags=re.IGNORECASE)
    normalized_subject = subject or "Uploaded Evidence"
    normalized_author = author or "Unknown / Uploaded PDF"
    normalized_year = year or str(datetime.utcnow().year)
    source_id = f"SRC-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    excerpt_records = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = normalize_whitespace(page.extract_text() or "")
        chunks = split_into_excerpt_chunks(text)
        for index, chunk in enumerate(chunks, start=1):
            excerpt_records.append(
                {
                    "sourceId": f"{source_id}-P{page_number:03d}-{index}",
                    "title": title,
                    "author": normalized_author,
                    "year": normalized_year,
                    "subject": normalized_subject,
                    "page": page_number,
                    "excerpt": chunk,
                    "keywords": derive_keywords(chunk),
                }
            )

    ingestion_status = "indexed" if excerpt_records else "needs_ocr"

    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO sources (
                source_id, title, author, year, subject, original_filename, upload_path,
                ingestion_status, excerpt_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                title,
                normalized_author,
                normalized_year,
                normalized_subject,
                original_name,
                str(file_path),
                ingestion_status,
                len(excerpt_records),
                datetime.utcnow().isoformat()
            )
        )
        source_row_id = cursor.lastrowid

        for record in excerpt_records:
            conn.execute(
                """
                INSERT INTO excerpts (
                    source_ref, source_row_id, title, author, year, subject, page,
                    excerpt, keywords_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["sourceId"],
                    source_row_id,
                    record["title"],
                    record["author"],
                    record["year"],
                    record["subject"],
                    record["page"],
                    record["excerpt"],
                    json.dumps(record["keywords"]),
                    datetime.utcnow().isoformat()
                )
            )
        conn.commit()

    return {
        "sourceId": source_id,
        "title": title,
        "subject": normalized_subject,
        "author": normalized_author,
        "year": normalized_year,
        "pageCount": len(reader.pages),
        "excerptCount": len(excerpt_records),
        "ingestionStatus": ingestion_status
    }


class EvidenceHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path):
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        suffix = file_path.suffix.lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(suffix, "application/octet-stream")

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path_name = parsed.path

        if path_name == "/api/health":
            self._send_json({"ok": True})
            return

        if path_name == "/api/stats":
            self._send_json(get_stats())
            return

        if path_name == "/api/subjects":
            self._send_json({"subjects": get_subjects()})
            return

        if path_name == "/api/sources":
            self._send_json({"sources": list_sources()})
            return

        if path_name == "/api/search":
            query = parse_qs(parsed.query)
            payload = search(
                query.get("q", [""])[0],
                query.get("subject", [""])[0],
                int(query.get("minTerms", ["2"])[0]),
            )
            self._send_json({"resultCount": len(payload), "results": payload})
            return

        target = PUBLIC_DIR / ("index.html" if path_name == "/" else path_name.lstrip("/"))
        self._send_file(target)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/upload":
            self.send_error(HTTPStatus.NOT_FOUND, "Route not found")
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            },
        )

        raw_files = form["pdfs"] if "pdfs" in form else []
        file_items = raw_files if isinstance(raw_files, list) else [raw_files]
        file_items = [item for item in file_items if getattr(item, "filename", None)]

        if not file_items:
            self._send_json({"error": "Choose at least one PDF file."}, status=HTTPStatus.BAD_REQUEST)
            return

        subject = form.getfirst("subject", "").strip()
        author = form.getfirst("author", "").strip()
        year = form.getfirst("year", "").strip()
        uploaded = []

        for item in file_items:
            original_name = safe_filename(Path(item.filename).name)
            destination = UPLOADS_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}-{original_name}"
            with destination.open("wb") as output_file:
                shutil.copyfileobj(item.file, output_file)
            uploaded.append(ingest_pdf(destination, original_name, subject, author, year))

        self._send_json({"uploaded": uploaded, "stats": get_stats()}, status=HTTPStatus.CREATED)


def main():
    init_schema()
    seed_database()
    server = ThreadingHTTPServer(("127.0.0.1", 3000), EvidenceHandler)
    print("Evidence Atlas running at http://127.0.0.1:3000")
    server.serve_forever()


if __name__ == "__main__":
    main()
