import json
import re
import sqlite3
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from email import policy
from email.parser import BytesParser
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
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "into", "is",
    "it", "of", "on", "or", "regarding", "show", "that", "the", "there", "this", "to", "was",
    "what", "when", "where", "which", "who", "why", "with", "evidence", "find", "about", "tell",
    "me"
}

RELATED_TERMS = {
    "abolition": ["freedom", "slavery", "enslaved"],
    "city": ["cities", "urban", "municipal"],
    "disease": ["illness", "mortality", "health"],
    "education": ["school", "schools", "learning"],
    "factory": ["industrial", "industry", "manufacturing"],
    "food": ["meat", "inspection", "packing"],
    "housing": ["tenement", "tenements", "slum", "slums"],
    "industrial": ["factory", "factories", "industry", "manufacturing"],
    "inspection": ["inspectors", "oversight", "regulation"],
    "law": ["legal", "statute", "legislation"],
    "poverty": ["poor", "slum", "slums", "tenement"],
    "public": ["municipal", "civic"],
    "reform": ["reforms", "improvement", "improvements", "change", "inspection", "administration"],
    "sanitary": ["sanitation", "drainage", "sewer", "sewers", "filth", "water"],
    "sanitation": ["sanitary", "drainage", "sewer", "sewers", "filth", "water", "ventilation"],
    "slavery": ["enslaved", "abolition", "freedom"],
    "urban": ["city", "cities", "municipal"],
    "water": ["drainage", "sewer", "sewers"],
}

JOB_LOCK = threading.Lock()
INGESTION_JOBS = {}


def tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [token for token in cleaned.split() if token and token not in STOP_WORDS]


def unique(values):
    return sorted(set(values))


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_term(term: str) -> str:
    term = term.lower().strip()
    if len(term) > 5 and term.endswith("ies"):
        return term[:-3] + "y"
    if len(term) > 4 and term.endswith("ing"):
        return term[:-3]
    if len(term) > 3 and term.endswith("ed"):
        return term[:-2]
    if len(term) > 4 and term.endswith("es"):
        return term[:-2]
    if len(term) > 3 and term.endswith("s"):
        return term[:-1]
    return term


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
        if len(candidate) <= 560:
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


def list_jobs():
    with JOB_LOCK:
        jobs = list(INGESTION_JOBS.values())
    return sorted(jobs, key=lambda item: item["createdAt"], reverse=True)


def get_job(job_id: str):
    with JOB_LOCK:
        job = INGESTION_JOBS.get(job_id)
        return dict(job) if job else None


def update_job(job_id: str, **updates):
    with JOB_LOCK:
        if job_id not in INGESTION_JOBS:
            return
        INGESTION_JOBS[job_id].update(updates)


def create_job(filename: str, subject: str):
    job_id = uuid.uuid4().hex
    job = {
        "jobId": job_id,
        "filename": filename,
        "subject": subject or "Uploaded Evidence",
        "status": "queued",
        "createdAt": datetime.utcnow().isoformat(),
        "pageCount": 0,
        "pagesProcessed": 0,
        "excerptCount": 0,
        "sourceId": None,
        "error": None,
        "ingestionStatus": "queued",
    }
    with JOB_LOCK:
        INGESTION_JOBS[job_id] = job
    return job


def extract_quoted_phrases(query: str) -> list[str]:
    return [normalize_whitespace(match) for match in re.findall(r'"([^"]+)"', query) if normalize_whitespace(match)]


def remove_quoted_content(query: str) -> str:
    return re.sub(r'"[^"]+"', " ", query)


def build_concept_phrases(tokens: list[str]) -> list[str]:
    phrases = []
    for size in (3, 2):
        for index in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[index:index + size])
            if phrase not in phrases:
                phrases.append(phrase)
    return phrases[:6]


def analyze_question(query: str):
    exact_phrases = extract_quoted_phrases(query)
    unquoted = remove_quoted_content(query)
    raw_tokens = tokenize(unquoted)
    normalized_terms = unique([normalize_term(token) for token in raw_tokens if len(token) > 2])
    concept_phrases = build_concept_phrases(raw_tokens)

    expanded_terms = set(normalized_terms)
    for term in normalized_terms:
        expanded_terms.update(RELATED_TERMS.get(term, []))

    return {
        "originalQuery": query,
        "exactPhrases": exact_phrases,
        "focusTerms": normalized_terms[:10],
        "expandedTerms": sorted(expanded_terms)[:24],
        "conceptPhrases": concept_phrases,
        "mode": "quoted-exact" if exact_phrases else "analyzed",
    }


def token_positions(tokens: list[str]):
    positions = defaultdict(list)
    for index, token in enumerate(tokens):
        positions[normalize_term(token)].append(index)
    return positions


def concept_present(phrase: str, positions_map, window: int = 10):
    phrase_terms = [normalize_term(term) for term in tokenize(phrase)]
    if not phrase_terms:
        return False
    if not all(term in positions_map for term in phrase_terms):
        return False

    anchor_positions = positions_map[phrase_terms[0]]
    for anchor in anchor_positions:
        if all(any(abs(pos - anchor) <= window for pos in positions_map[term]) for term in phrase_terms[1:]):
            return True
    return False


def score_excerpt(row, analysis):
    source_ref, title, author, year, subject, page, excerpt, keywords_json = row
    keywords = json.loads(keywords_json or "[]")
    full_text = " ".join([title, author, subject, excerpt, *keywords])
    raw_tokens = re.findall(r"[a-z0-9]+", full_text.lower())
    normalized_tokens = [normalize_term(token) for token in raw_tokens]
    normalized_set = set(normalized_tokens)
    positions_map = token_positions(raw_tokens)

    exact_phrase_hits = []
    for phrase in analysis["exactPhrases"]:
        lowered_phrase = normalize_whitespace(phrase.lower())
        if lowered_phrase in normalize_whitespace(excerpt.lower()) or lowered_phrase in normalize_whitespace(title.lower()):
            exact_phrase_hits.append(phrase)

    if analysis["exactPhrases"] and len(exact_phrase_hits) != len(analysis["exactPhrases"]):
        return None

    exact_term_hits = [term for term in analysis["focusTerms"] if term in normalized_set]
    expanded_hits = [term for term in analysis["expandedTerms"] if term in normalized_set and term not in exact_term_hits]
    concept_hits = [phrase for phrase in analysis["conceptPhrases"] if concept_present(phrase, positions_map)]

    title_text = f"{title} {author} {subject}".lower()
    title_focus_hits = [term for term in analysis["focusTerms"] if term in title_text]

    score = 0
    score += len(exact_phrase_hits) * 120
    score += len(concept_hits) * 22
    score += len(exact_term_hits) * 8
    score += len(expanded_hits[:6]) * 3
    score += len(title_focus_hits) * 10

    if score <= 0:
        return None

    match_labels = []
    match_labels.extend([f'"{phrase}"' for phrase in exact_phrase_hits])
    match_labels.extend(concept_hits[:4])
    match_labels.extend(exact_term_hits[:6])
    if not match_labels:
        match_labels.extend(expanded_hits[:4])

    return {
        "sourceId": source_ref,
        "title": title,
        "author": author,
        "year": year,
        "subject": subject,
        "page": int(page),
        "excerpt": excerpt,
        "matches": unique(match_labels),
        "matchCount": len(unique(match_labels)),
        "score": score,
        "exactPhraseMatch": bool(exact_phrase_hits),
        "conceptHits": concept_hits,
        "focusHits": exact_term_hits,
    }


def search(query: str, subject: str, source_id: str):
    normalized_query = query.strip()
    analysis = analyze_question(normalized_query)
    if not normalized_query:
        return {"analysis": analysis, "results": []}

    with connect() as conn:
        if subject and source_id:
            rows = conn.execute(
                """
                SELECT source_ref, title, author, year, subject, page, excerpt, keywords_json
                FROM excerpts
                WHERE subject = ? AND source_row_id IN (
                    SELECT id FROM sources WHERE source_id = ?
                )
                """,
                (subject, source_id),
            ).fetchall()
        elif subject:
            rows = conn.execute(
                """
                SELECT source_ref, title, author, year, subject, page, excerpt, keywords_json
                FROM excerpts
                WHERE subject = ?
                """,
                (subject,),
            ).fetchall()
        elif source_id:
            rows = conn.execute(
                """
                SELECT source_ref, title, author, year, subject, page, excerpt, keywords_json
                FROM excerpts
                WHERE source_row_id IN (
                    SELECT id FROM sources WHERE source_id = ?
                )
                """,
                (source_id,),
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
        scored = score_excerpt(row, analysis)
        if scored:
            matches.append(scored)

    matches.sort(key=lambda item: (-item["score"], -int(item["exactPhraseMatch"]), item["page"]))
    return {"analysis": analysis, "results": matches[:50]}


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", name)


def parse_multipart_form_data(headers, body: bytes):
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        return {}, []

    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )

    fields = {}
    files = []

    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if not name:
            continue

        if filename:
            files.append(
                {
                    "name": name,
                    "filename": filename,
                    "content": payload,
                }
            )
        else:
            fields[name] = payload.decode(part.get_content_charset() or "utf-8", errors="replace").strip()

    return fields, files


def ingest_pdf(file_path: Path, original_name: str, subject: str, author: str, year: str, progress_callback=None):
    reader = PdfReader(str(file_path))
    title = re.sub(r"\.pdf$", "", original_name, flags=re.IGNORECASE)
    normalized_subject = subject or "Uploaded Evidence"
    normalized_author = author or "Unknown / Uploaded PDF"
    normalized_year = year or str(datetime.utcnow().year)
    source_id = f"SRC-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    excerpt_records = []
    total_pages = len(reader.pages)

    if progress_callback:
        progress_callback(0, total_pages, 0, "processing")

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
        if progress_callback:
            progress_callback(page_number, total_pages, len(excerpt_records), "processing")

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

    if progress_callback:
        progress_callback(total_pages, total_pages, len(excerpt_records), "completed")

    return {
        "sourceId": source_id,
        "title": title,
        "subject": normalized_subject,
        "author": normalized_author,
        "year": normalized_year,
        "pageCount": total_pages,
        "excerptCount": len(excerpt_records),
        "ingestionStatus": ingestion_status
    }


def process_job(job_id: str, file_path: Path, original_name: str, subject: str, author: str, year: str):
    try:
        update_job(job_id, status="processing", ingestionStatus="processing")

        def progress_callback(processed_pages, total_pages, excerpt_count, status):
            update_job(
                job_id,
                status=status,
                ingestionStatus=status,
                pagesProcessed=processed_pages,
                pageCount=total_pages,
                excerptCount=excerpt_count,
            )

        result = ingest_pdf(file_path, original_name, subject, author, year, progress_callback=progress_callback)
        update_job(
            job_id,
            status="completed",
            ingestionStatus=result["ingestionStatus"],
            pageCount=result["pageCount"],
            pagesProcessed=result["pageCount"],
            excerptCount=result["excerptCount"],
            sourceId=result["sourceId"],
        )
    except Exception as error:
        update_job(job_id, status="failed", ingestionStatus="failed", error=str(error))


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

        if path_name == "/api/jobs":
            self._send_json({"jobs": list_jobs()})
            return

        if path_name.startswith("/api/jobs/"):
            job_id = path_name.rsplit("/", 1)[-1]
            job = get_job(job_id)
            if not job:
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(job)
            return

        if path_name == "/api/search":
            query = parse_qs(parsed.query)
            payload = search(
                query.get("q", [""])[0],
                query.get("subject", [""])[0],
                query.get("sourceId", [""])[0],
            )
            self._send_json({
                "resultCount": len(payload["results"]),
                "analysis": payload["analysis"],
                "results": payload["results"],
            })
            return

        target = PUBLIC_DIR / ("index.html" if path_name == "/" else path_name.lstrip("/"))
        self._send_file(target)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/upload":
            self.send_error(HTTPStatus.NOT_FOUND, "Route not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        fields, file_items = parse_multipart_form_data(self.headers, body)
        file_items = [item for item in file_items if item.get("name") == "pdfs" and item.get("filename")]

        if not file_items:
            self._send_json({"error": "Choose at least one PDF file."}, status=HTTPStatus.BAD_REQUEST)
            return

        subject = fields.get("subject", "").strip()
        author = fields.get("author", "").strip()
        year = fields.get("year", "").strip()
        jobs = []

        for item in file_items:
            original_name = safe_filename(Path(item["filename"]).name)
            destination = UPLOADS_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}-{original_name}"
            with destination.open("wb") as output_file:
                output_file.write(item["content"])

            job = create_job(original_name, subject)
            jobs.append(job)
            worker = threading.Thread(
                target=process_job,
                args=(job["jobId"], destination, original_name, subject, author, year),
                daemon=True,
            )
            worker.start()

        self._send_json(
            {
                "jobs": jobs,
                "stats": get_stats(),
                "message": "Files uploaded. Ingestion is running in the background."
            },
            status=HTTPStatus.ACCEPTED
        )


def main():
    init_schema()
    seed_database()
    server = ThreadingHTTPServer(("127.0.0.1", 3000), EvidenceHandler)
    print("Evidence Atlas running at http://127.0.0.1:3000")
    server.serve_forever()


if __name__ == "__main__":
    main()
