# Evidence Atlas

Evidence Atlas is a retrieval-only evidence finder for scanned books. It stores uploaded PDFs, indexes excerpt records into a local SQLite database, and only returns exact cited passages with source metadata.

## What it does

- Accepts a user question or subject query.
- Searches a persistent local evidence database instead of an in-memory browser array.
- Accepts PDF uploads through the web UI and stores them on the server.
- Extracts page text from text-based PDFs and creates page-level excerpt records.
- Marks image-only scans as `needs_ocr` instead of pretending they were searchable.
- Supports exact-phrase mode and source-specific filtering for tighter citation lookup.
- Returns exact excerpts, page numbers, source IDs, and metadata.
- Avoids generative answers, summaries, and suggestions.

## Project structure

- `server.py` starts the local HTTP server and API.
- `public/` contains the retrieval-only client UI.
- `data/books.json` seeds the database on first run.
- `uploads/` is created at runtime for stored PDFs.

## Run locally

Run [run-local.bat](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\run-local.bat) or [run-local.ps1](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\run-local.ps1).

What it does automatically:

- Creates `.venv` on first run.
- Installs or refreshes requirements only when `requirements.txt` changes.
- Starts the local server if it is not already running.
- Opens `http://127.0.0.1:3000` in your browser.

To stop the local background server, run [stop-local.ps1](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\stop-local.ps1).

## Search behavior

- Search uses term overlap only.
- Search can also require exact phrase hits.
- Results are ranked by exact-phrase hit first, then matched term count, then page number.
- Every result is shown as an exact excerpt with citation metadata.
- The UI does not generate narrative answers.

## Upload behavior

1. Choose one or more PDF files in the upload panel.
2. Optionally provide subject, author, or year overrides.
3. The server stores each PDF in `uploads/`.
4. Text-based PDFs are parsed into excerpt records and written to the database.
5. PDFs without extractable text are saved and flagged as `needs_ocr`.

## Important limitation

- This version has honest OCR handling, not fake OCR.
- Text-layer PDFs work immediately.
- Image-only scanned PDFs are persisted and clearly marked for OCR follow-up.
- Full OCR for image-only scans is the next upgrade path.

## Good next upgrades

- Add Tesseract-based OCR for image-only scanned PDFs.
- Add exact phrase search and boolean operators.
- Add scanned-page image previews alongside excerpt citations.
- Add authentication and per-library collections.
