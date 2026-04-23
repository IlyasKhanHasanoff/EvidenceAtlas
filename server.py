import base64
import json
import os
import re
import threading
import uuid
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request
from urllib.parse import urlparse

from pypdf import PdfReader, PdfWriter

from evidence_engine import answer_question

ROOT = Path(__file__).parent
DOCS_DIR = ROOT / "docs"
LIBRARY_DIR = DOCS_DIR / "library"
LIBRARY_ASSETS_DIR = ROOT / "library-assets"
PDFS_DIR = LIBRARY_ASSETS_DIR / "pdfs"
INBOX_DIR = ROOT / "library-inbox"
REPO_DROP_DIR = ROOT / "repo-pdf-drop"
INDEX_PATH = LIBRARY_DIR / "index.json"
MANIFEST_PATH = LIBRARY_DIR / "source-manifest.json"
ENV_PATH = ROOT / ".env"

JOB_LOCK = threading.Lock()
LIBRARY_LOCK = threading.Lock()
INGESTION_JOBS = {}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "into", "is",
    "it", "of", "on", "or", "that", "the", "there", "this", "to", "was", "what", "when", "where",
    "which", "who", "why", "with"
}

OCR_BATCH_SIZE = 12


def load_env_from_file():
    if os.environ.get("OPENAI_API_KEY") or not ENV_PATH.exists():
        return

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [token for token in cleaned.split() if token and token not in STOP_WORDS]


def derive_keywords(text: str) -> list[str]:
    return sorted(set(tokenize(text)))[:12]


def clean_extracted_text(text: str) -> str:
    lines = []

    for raw_line in (text or "").splitlines():
        line = normalize_whitespace(raw_line)
        if not line:
            continue
        if re.match(r"^\d+\s*-\s*THE BOOK OF\b", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^\(?\d+\)?\s*CHAPTER\b", line, flags=re.IGNORECASE):
            continue
        if re.search(r"\bCONTENTS OF VOLUME\b", line, flags=re.IGNORECASE):
            continue
        if re.search(r"\bEND OF VOLUME\b", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^page\s+\d+$", line, flags=re.IGNORECASE):
            continue
        if len(line) < 3:
            continue

        ascii_ratio = sum(1 for char in line if ord(char) < 128) / max(1, len(line))
        if ascii_ratio < 0.65:
            continue

        symbol_ratio = sum(1 for char in line if not char.isalnum() and char not in " .,;:'\"!?()-/") / max(1, len(line))
        if symbol_ratio > 0.22:
            continue

        line = re.sub(r"\s+([,.;:!?])", r"\1", line)
        line = re.sub(r"([,.;:!?])([A-Za-z])", r"\1 \2", line)
        line = re.sub(r"\(\s+", "(", line)
        line = re.sub(r"\s+\)", ")", line)
        lines.append(line)

    cleaned = normalize_whitespace(" ".join(lines))
    cleaned = re.sub(r"\b(?:THE BOOK OF|CHAPTER)\b.*?(?=[A-Z][a-z]|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[[^\]]{0,20}[^\x00-\x7F][^\]]*\]", "", cleaned)
    cleaned = re.sub(r"[^\x00-\x7F]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -\"'")


def finalize_excerpt(chunk: str) -> str:
    excerpt = normalize_whitespace(chunk)
    for marker in ["Narrated ", "Allah's Messenger", "The Prophet", "And the Statement of Allah"]:
        index = excerpt.find(marker)
        if index > 0 and index < 220:
            excerpt = excerpt[index:]
            break

    excerpt = re.sub(r"^\d+\s*[-–]?\s*THE BOOK OF[A-Z0-9' .:/()-]+", "", excerpt, flags=re.IGNORECASE)
    excerpt = re.sub(r"^\(?\d+\)?\s*(?:CHAPTER|CHAFFER)\.?", "", excerpt, flags=re.IGNORECASE)
    excerpt = re.sub(r"\[[^\]]*\]", "", excerpt)
    excerpt = re.sub(r"\b(?=\w*[A-Za-z])(?=\w*\d)\w+\b", "", excerpt)
    excerpt = re.sub(r"\b[A-Za-z]{0,3}[/:;][A-Za-z0-9]{0,4}\b", "", excerpt)
    excerpt = re.sub(r"\.{3,}", " ", excerpt)
    excerpt = re.sub(r"\s*-\s*", " - ", excerpt)
    excerpt = re.sub(r"\s+", " ", excerpt)
    excerpt = re.sub(r"([.!?])\s+(?:[A-Za-z]{1,3}\s+){2,10}[A-Za-z]{1,3}\s*$", r"\1", excerpt)
    excerpt = re.sub(r"([.!?])\s+[A-Za-z]{1,3}(?:\s+[A-Za-z]{1,3}){0,6}\s*$", r"\1", excerpt)
    return excerpt.strip(" -\"'")


def page_needs_ocr(raw_text: str, chunks: list[str]) -> bool:
    normalized = normalize_whitespace(raw_text)
    if not normalized:
        return True
    cleaned = clean_extracted_text(normalized)
    if len(cleaned) < 120:
        return True
    if not chunks:
        return True
    alpha_ratio = sum(1 for char in cleaned if char.isalpha() or char.isspace()) / max(1, len(cleaned))
    if alpha_ratio < 0.72:
        return True
    return False


def is_readable_chunk(chunk: str) -> bool:
    if len(chunk) < 120:
        return False
    if re.search(r"\bCONTENTS OF VOLUME\b", chunk, flags=re.IGNORECASE):
        return False
    if re.search(r"\bEND OF VOLUME\b", chunk, flags=re.IGNORECASE):
        return False
    if chunk.upper().count("THE BOOK OF") >= 1 and "Narrated" not in chunk:
        return False
    if chunk.upper().count("CHAPTER") >= 2 or chunk.upper().count("CHAFFER") >= 2:
        return False
    if re.search(r"\.{4,}", chunk):
        return False
    return True


def split_into_excerpt_chunks(text: str) -> list[str]:
    cleaned = clean_extracted_text(text)
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

    finalized = [finalize_excerpt(chunk) for chunk in chunks]
    return [chunk for chunk in finalized if is_readable_chunk(chunk)]


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
            files.append({"name": name, "filename": filename, "content": payload})
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace").strip()

    return fields, files


def ensure_library_index():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    LIBRARY_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    REPO_DROP_DIR.mkdir(parents=True, exist_ok=True)

    if INDEX_PATH.exists():
        migrate_library_schema()
        return
    save_library({"generatedAt": datetime.utcnow().isoformat(), "sources": [], "records": []})


def migrate_library_schema():
    library = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    changed = False

    for source in library.get("sources", []):
        if "topic" not in source:
            source["topic"] = source.get("subject")
            changed = True
        if "subject" in source and "subSubject" in source and source.get("subSubject") and source.get("subject") == source.get("topic"):
            source["subject"] = source.get("subSubject")
            changed = True
        if "subSubject" in source:
            source.pop("subSubject", None)
            changed = True
        if "originalFilename" not in source:
            source["originalFilename"] = None
            changed = True
        pdf_path = source.get("pdfPath", "")
        if isinstance(pdf_path, str) and pdf_path.startswith("./library/pdfs/"):
            source["pdfPath"] = build_pdf_route(Path(pdf_path).name)
            changed = True

    for record in library.get("records", []):
        if "topic" not in record:
            record["topic"] = record.get("subject")
            changed = True
        if "subject" in record and "subSubject" in record and record.get("subSubject") and record.get("subject") == record.get("topic"):
            record["subject"] = record.get("subSubject")
            changed = True
        if "subSubject" in record:
            record.pop("subSubject", None)
            changed = True
        if "originalFilename" not in record:
            record["originalFilename"] = None
            changed = True
        pdf_path = record.get("pdfPath", "")
        if isinstance(pdf_path, str) and pdf_path.startswith("./library/pdfs/"):
            record["pdfPath"] = build_pdf_route(Path(pdf_path).name)
            changed = True

    if changed:
        INDEX_PATH.write_text(json.dumps(library, indent=2), encoding="utf-8")


def load_library():
    ensure_library_index()
    with LIBRARY_LOCK:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def save_library(library):
    library["generatedAt"] = datetime.utcnow().isoformat()
    with LIBRARY_LOCK:
        INDEX_PATH.write_text(json.dumps(library, indent=2), encoding="utf-8")


def existing_original_filenames(library) -> set[str]:
    return {
        item["originalFilename"].lower()
        for item in library.get("sources", [])
        if item.get("originalFilename")
    }


def list_pdf_files(directory: Path):
    ensure_library_index()
    return sorted(
        [
            {
                "filename": path.name,
                "size": path.stat().st_size,
                "modifiedAt": datetime.utcfromtimestamp(path.stat().st_mtime).isoformat(),
            }
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        ],
        key=lambda item: item["filename"].lower(),
    )


def load_source_manifest():
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def metadata_for_filename(filename: str):
    return load_source_manifest().get(filename, {})


def build_pdf_route(file_name: str) -> str:
    return f"/library-pdfs/{file_name}"


def resolve_pdf_asset(path_name: str):
    relative = Path(path_name.removeprefix("/library-pdfs/"))
    target = (PDFS_DIR / relative).resolve()
    if PDFS_DIR not in target.parents and target != PDFS_DIR:
        return None
    return target


def chunked(values, size):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def build_pdf_subset_bytes(reader: PdfReader, page_numbers: list[int]) -> bytes:
    from io import BytesIO

    writer = PdfWriter()
    for page_number in page_numbers:
        writer.add_page(reader.pages[page_number - 1])
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def parse_json_output(raw_text: str):
    text = (raw_text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def call_openai_pdf_ocr(pdf_bytes: bytes, filename: str, page_numbers: list[int]):
    load_env_from_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {}

    model = os.environ.get("OPENAI_OCR_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "instructions": (
            "You are extracting readable text from scanned PDF pages for indexing. "
            "Do not summarize. Do not explain. "
            "Return strict JSON with one key named pages. "
            "pages must be an array of objects with keys page and text. "
            "page must exactly match the original page number supplied in the prompt. "
            "text must contain a clean transcription of the page, with normalized whitespace. "
            "Keep wording faithful. Skip only decorative headers, footers, and isolated page numbers when they add no meaning."
        ),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Transcribe these PDF pages for search indexing.\n"
                            f"Original page numbers in this file batch: {', '.join(str(item) for item in page_numbers)}\n"
                            "Return JSON only."
                        ),
                    },
                    {
                        "type": "input_file",
                        "filename": filename,
                        "file_data": f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode('ascii')}",
                    },
                ],
            }
        ],
    }

    req = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
        parsed = parse_json_output(body.get("output_text", ""))
    except Exception:
        return {}

    if not isinstance(parsed, dict):
        return {}

    pages = {}
    valid_numbers = set(page_numbers)
    for item in parsed.get("pages", []):
        if not isinstance(item, dict):
            continue
        try:
            page_number = int(item.get("page"))
        except (TypeError, ValueError):
            continue
        if page_number not in valid_numbers:
            continue
        text = normalize_whitespace(item.get("text", ""))
        if text:
            pages[page_number] = text
    return pages


def ocr_pages_with_openai(reader: PdfReader, page_numbers: list[int], original_name: str, progress_callback=None):
    extracted = {}
    if not page_numbers:
        return extracted

    batches = list(chunked(page_numbers, OCR_BATCH_SIZE))
    total_batches = len(batches)
    for batch_index, batch in enumerate(batches, start=1):
        if progress_callback:
            progress_callback(0, len(batch), 0, f"ocr-batch-{batch_index}-of-{total_batches}")
        pdf_bytes = build_pdf_subset_bytes(reader, batch)
        batch_result = call_openai_pdf_ocr(pdf_bytes, original_name, batch)
        extracted.update(batch_result)
    return extracted


def create_job(filename: str, topic: str, subject: str):
    job_id = uuid.uuid4().hex
    job = {
        "jobId": job_id,
        "filename": filename,
        "topic": topic or "Uploaded Evidence",
        "subject": subject or None,
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


def update_job(job_id: str, **updates):
    with JOB_LOCK:
        if job_id in INGESTION_JOBS:
            INGESTION_JOBS[job_id].update(updates)


def list_jobs():
    with JOB_LOCK:
        jobs = list(INGESTION_JOBS.values())
    return sorted(jobs, key=lambda item: item["createdAt"], reverse=True)


def get_job(job_id: str):
    with JOB_LOCK:
        job = INGESTION_JOBS.get(job_id)
        return dict(job) if job else None


def upsert_source_and_records(source, records):
    library = load_library()

    library["sources"] = [item for item in library["sources"] if item["sourceId"] != source["sourceId"]]
    library["records"] = [item for item in library["records"] if item["sourceRef"] != source["sourceId"]]

    library["sources"].append(source)
    library["records"].extend(records)
    save_library(library)


def ingest_pdf_into_library(
    file_path: Path,
    original_name: str,
    topic: str,
    subject: str,
    author: str,
    year: str,
    progress_callback=None,
):
    reader = PdfReader(str(file_path))
    manifest_metadata = metadata_for_filename(original_name)
    title = manifest_metadata.get("title") or re.sub(r"\.pdf$", "", original_name, flags=re.IGNORECASE)
    normalized_topic = topic or manifest_metadata.get("topic") or "Uploaded Evidence"
    normalized_subject = subject or manifest_metadata.get("subject") or None
    normalized_author = author or "Unknown / Uploaded PDF"
    if manifest_metadata.get("author") and not author:
        normalized_author = manifest_metadata["author"]
    normalized_year = year or str(datetime.utcnow().year)
    if manifest_metadata.get("year") and not year:
        normalized_year = manifest_metadata["year"]
    source_id = f"SRC-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    total_pages = len(reader.pages)
    records = []
    pages_needing_ocr = []
    used_ocr = False

    if progress_callback:
        progress_callback(0, total_pages, 0, "processing")

    for page_number, page in enumerate(reader.pages, start=1):
        text = normalize_whitespace(page.extract_text() or "")
        chunks = split_into_excerpt_chunks(text)
        if page_needs_ocr(text, chunks):
            pages_needing_ocr.append(page_number)
        for index, chunk in enumerate(chunks, start=1):
            records.append(
                {
                    "sourceId": f"{source_id}-P{page_number:03d}-{index}",
                    "sourceRef": source_id,
                    "title": title,
                    "author": normalized_author,
                    "year": normalized_year,
                    "topic": normalized_topic,
                    "subject": normalized_subject,
                    "page": page_number,
                    "excerpt": chunk,
                    "keywords": derive_keywords(chunk),
                    "pdfPath": build_pdf_route(file_path.name),
                    "originalFilename": original_name,
                }
            )
        if progress_callback:
            progress_callback(page_number, total_pages, len(records), "processing")

    if pages_needing_ocr:
        if progress_callback:
            progress_callback(0, len(pages_needing_ocr), len(records), "ocr-processing")
        ocr_pages = ocr_pages_with_openai(reader, pages_needing_ocr, original_name, progress_callback=progress_callback)
        if ocr_pages:
            used_ocr = True
        if used_ocr:
            page_set = set(pages_needing_ocr)
            records = [record for record in records if record["page"] not in page_set]
        for page_number in pages_needing_ocr:
            ocr_text = ocr_pages.get(page_number, "")
            if not ocr_text:
                continue
            chunks = split_into_excerpt_chunks(ocr_text)
            for index, chunk in enumerate(chunks, start=1):
                records.append(
                    {
                        "sourceId": f"{source_id}-P{page_number:03d}-OCR{index}",
                        "sourceRef": source_id,
                        "title": title,
                        "author": normalized_author,
                        "year": normalized_year,
                        "topic": normalized_topic,
                        "subject": normalized_subject,
                        "page": page_number,
                        "excerpt": chunk,
                        "keywords": derive_keywords(chunk),
                        "pdfPath": build_pdf_route(file_path.name),
                        "originalFilename": original_name,
                    }
                )

    if records:
        ingestion_status = "ocr_indexed" if used_ocr else "indexed"
    else:
        ingestion_status = "needs_ocr"
    source = {
        "sourceId": source_id,
        "title": title,
        "author": normalized_author,
        "year": normalized_year,
        "topic": normalized_topic,
        "subject": normalized_subject,
        "pdfPath": build_pdf_route(file_path.name),
        "originalFilename": original_name,
        "ingestionStatus": ingestion_status,
        "ocrUsed": used_ocr,
        "excerptCount": len(records),
    }

    upsert_source_and_records(source, records)

    if progress_callback:
        progress_callback(total_pages, total_pages, len(records), "completed")

    return {
        "sourceId": source_id,
        "title": title,
        "topic": normalized_topic,
        "subject": normalized_subject,
        "author": normalized_author,
        "year": normalized_year,
        "pageCount": total_pages,
        "excerptCount": len(records),
        "ingestionStatus": ingestion_status,
    }


def process_job(job_id: str, file_path: Path, original_name: str, topic: str, subject: str, author: str, year: str):
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

        result = ingest_pdf_into_library(file_path, original_name, topic, subject, author, year, progress_callback)
        update_job(
            job_id,
            status="completed",
            ingestionStatus=result["ingestionStatus"],
            pagesProcessed=result["pageCount"],
            pageCount=result["pageCount"],
            excerptCount=result["excerptCount"],
            sourceId=result["sourceId"],
        )
    except Exception as error:
        update_job(job_id, status="failed", ingestionStatus="failed", error=str(error))


def queue_file_for_ingestion(file_path: Path, original_name: str, topic: str, subject: str, author: str, year: str):
    job = create_job(original_name, topic, subject)
    worker = threading.Thread(
        target=process_job,
        args=(job["jobId"], file_path, original_name, topic, subject, author, year),
        daemon=True,
    )
    worker.start()
    return job


def list_unindexed_library_pdfs():
    library = load_library()
    known_files = existing_original_filenames(library)
    return [
        item for item in list_pdf_files(PDFS_DIR)
        if item["filename"].lower() not in known_files and item["filename"] != ".gitkeep"
    ]


class AppHandler(BaseHTTPRequestHandler):
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
            ".webmanifest": "application/manifest+json; charset=utf-8",
            ".pdf": "application/pdf",
            ".png": "image/png",
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

        if path_name.startswith("/library-pdfs/"):
            target = resolve_pdf_asset(path_name)
            if not target:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid PDF path")
                return
            self._send_file(target)
            return

        if path_name == "/api/health":
            self._send_json({"ok": True, "mode": "local-app"})
            return

        if path_name == "/api/jobs":
            self._send_json({"jobs": list_jobs()})
            return

        if path_name == "/api/inbox":
            self._send_json({"files": list_pdf_files(INBOX_DIR)})
            return

        if path_name == "/api/repo-drop":
            self._send_json({"files": list_pdf_files(REPO_DROP_DIR)})
            return

        if path_name == "/api/library-pdfs":
            self._send_json({"files": list_unindexed_library_pdfs()})
            return

        if path_name.startswith("/api/jobs/"):
            job_id = path_name.rsplit("/", 1)[-1]
            job = get_job(job_id)
            if not job:
                self._send_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(job)
            return

        if path_name == "/api/library":
            self._send_json(load_library())
            return

        target = DOCS_DIR / ("index.html" if path_name == "/" else path_name.lstrip("/"))
        self._send_file(target)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/answer":
            fields = parse_json_body(self)
            query = fields.get("query", "").strip()
            if not query:
                self._send_json({"error": "Enter a question first."}, status=HTTPStatus.BAD_REQUEST)
                return

            self._send_json(
                answer_question(
                    query,
                    topic=fields.get("topic", "").strip(),
                    subject=fields.get("subject", "").strip(),
                    source_id=fields.get("sourceId", "").strip(),
                )
            )
            return

        if parsed.path in {"/api/import-inbox", "/api/import-repo-drop"}:
            fields = parse_json_body(self)
            topic = fields.get("topic", "").strip()
            subject = fields.get("subject", "").strip()
            author = fields.get("author", "").strip()
            year = fields.get("year", "").strip()
            library = load_library()
            known_files = existing_original_filenames(library)
            jobs = []
            skipped = []

            if parsed.path == "/api/import-inbox":
                is_inbox_import = True
                source_directory = INBOX_DIR
                source_label = "Inbox PDFs"
            else:
                is_inbox_import = False
                source_directory = REPO_DROP_DIR
                source_label = "Repo drop PDFs"

            for inbox_file in source_directory.iterdir():
                if not inbox_file.is_file() or inbox_file.suffix.lower() != ".pdf":
                    continue
                original_name = safe_filename(inbox_file.name)
                if original_name.lower() in known_files:
                    skipped.append(original_name)
                    continue

                destination = PDFS_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}-{original_name}"
                if is_inbox_import:
                    inbox_file.replace(destination)
                else:
                    destination.write_bytes(inbox_file.read_bytes())
                jobs.append(queue_file_for_ingestion(destination, original_name, topic, subject, author, year))
                known_files.add(original_name.lower())

            self._send_json(
                {
                    "jobs": jobs,
                    "skipped": skipped,
                    "library": load_library(),
                    "message": f"{source_label} were copied into the repo library and queued for indexing."
                    if jobs else f"No new files were queued from {source_label.lower()}."
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if parsed.path == "/api/import-library-pdfs":
            fields = parse_json_body(self)
            topic = fields.get("topic", "").strip()
            subject = fields.get("subject", "").strip()
            author = fields.get("author", "").strip()
            year = fields.get("year", "").strip()
            library = load_library()
            known_files = existing_original_filenames(library)
            jobs = []
            skipped = []

            for item in list_pdf_files(PDFS_DIR):
                if item["filename"] == ".gitkeep":
                    continue
                original_name = safe_filename(item["filename"])
                if original_name.lower() in known_files:
                    skipped.append(original_name)
                    continue
                jobs.append(queue_file_for_ingestion(PDFS_DIR / item["filename"], original_name, topic, subject, author, year))
                known_files.add(original_name.lower())

            self._send_json(
                {
                    "jobs": jobs,
                    "skipped": skipped,
                    "library": load_library(),
                    "message": "Committed library PDFs were queued for indexing."
                    if jobs else "No new committed library PDFs were queued."
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

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

        topic = fields.get("topic", "").strip()
        subject = fields.get("subject", "").strip()
        author = fields.get("author", "").strip()
        year = fields.get("year", "").strip()
        library = load_library()
        known_files = existing_original_filenames(library)
        jobs = []
        skipped = []

        for item in file_items:
            original_name = safe_filename(Path(item["filename"]).name)
            if original_name.lower() in known_files:
                skipped.append(original_name)
                continue
            destination = PDFS_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}-{original_name}"
            destination.write_bytes(item["content"])
            jobs.append(queue_file_for_ingestion(destination, original_name, topic, subject, author, year))
            known_files.add(original_name.lower())

        self._send_json(
            {
                "jobs": jobs,
                "skipped": skipped,
                "library": load_library(),
                "message": "Files copied into the repo library and queued for indexing."
                if jobs else "All selected PDFs are already part of the repo library."
            },
            status=HTTPStatus.ACCEPTED,
        )


def parse_json_body(handler):
    content_length = int(handler.headers.get("Content-Length", "0"))
    if content_length <= 0:
        return {}

    raw_body = handler.rfile.read(content_length)
    try:
        return json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def main():
    ensure_library_index()
    server = ThreadingHTTPServer(("127.0.0.1", 3000), AppHandler)
    print("Evidence Atlas app running at http://127.0.0.1:3000")
    server.serve_forever()


if __name__ == "__main__":
    main()
