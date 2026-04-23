# Evidence Atlas

Evidence Atlas is now a repo-backed app rather than only a local website. The same committed library files power:

- local app mode, where you can add new PDFs into the repo
- Vercel mode, where anyone with the link can query the shared evidence index without uploading anything

## Core model

- Shared library data lives in [docs/library/index.json](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\library\index.json)
- Local repo PDFs live in `library-assets/pdfs/`
- Shared PDF metadata lives in [docs/library/source-manifest.json](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\library\source-manifest.json)
- Large local import staging lives in [library-inbox](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\library-inbox)
- Developer-shared PDF staging lives in [repo-pdf-drop](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\repo-pdf-drop)
- The app UI lives in [docs/index.html](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\index.html), [docs/app.js](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\app.js), and [docs/styles.css](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\styles.css)
- Local mode uses [server.py](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\server.py) only to add books into that repo library and serve the app locally

## What changed

- Search is now client-side against the committed library index, so Vercel can serve the app without bundling the raw PDF library.
- Anyone with the app link can open the shared library immediately with no upload step.
- Local uploads are copied into `library-assets/pdfs/` so they stay in the repo without bloating the Vercel deployment bundle.
- Large PDFs can be dropped into `library-inbox/` and imported without pushing the whole file through the browser.
- Shared developer PDFs can be committed into `repo-pdf-drop/` and imported into the library without removing them from that repo folder.
- Quoted words or phrases are treated as exact constraints; everything else uses question-analysis-based retrieval.
- Sources can now be organized as `topic -> subject`, and the filters include searchable topic and subject dropdowns.
- The app can now answer a question from the indexed evidence and cite the pages it used. If the evidence is weak, it says so instead of inventing an answer.
- The app is installable as a lightweight PWA via the web manifest and service worker.

## Run locally

Run [run-local.bat](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\run-local.bat) or [run-local.ps1](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\run-local.ps1).

That will:

- create `.venv` on first run
- install or refresh requirements when needed
- start the local companion server
- open `http://127.0.0.1:3000`
- let you install the app shell from the browser as a desktop-style app if you want

To stop the local companion server, run [stop-local.ps1](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\stop-local.ps1).

## Use on Vercel

This repo is also ready for Vercel:

- the shared app is served from `docs/`
- `/api/health` stays read-only on Vercel so the UI does not expose local-only upload behavior
- `/api/answer` can produce evidence-grounded answers on Vercel too if `OPENAI_API_KEY` is configured in the Vercel project environment
- local ingestion still happens through `server.py` when you run the project on your own machine
- raw PDFs are excluded from the Vercel deployment by `.vercelignore`
- source PDFs should eventually live in object storage if you want them publicly downloadable at scale
- if `BLOB_READ_WRITE_TOKEN` is configured locally, indexed PDFs can be synced to Vercel Blob and the shared index will use those public Blob URLs

## Upload behavior

- In local mode, the upload panel is enabled.
- Browser uploads copy PDFs into `library-assets/pdfs/`.
- Large books can be copied into `library-inbox/` first, then imported from the app with one button.
- Developers can also commit PDFs into `repo-pdf-drop/`, push them, and import them from the app with one button.
- PDFs already committed into `library-assets/pdfs/` can be indexed from the app using the shared `source-manifest.json`.
- The local app can also sync indexed PDFs to Vercel Blob so the shared deployment can link to them without bundling them.
- If PDFs are already in your Blob store, the local app can match them by filename and rewrite the library index to those existing Blob URLs.
- A background job extracts excerpts and updates `docs/library/index.json`.
- Each source can carry a `topic` plus an optional `subject`.
- Duplicate original filenames are skipped so the same book is not imported repeatedly.
- After that, commit and push the changed library files so Vercel visitors get the new indexed evidence too.

## Answering behavior

- The answer panel uses only the retrieved library evidence for the current question.
- It returns a short answer plus page citations to the excerpts it used.
- If `OPENAI_API_KEY` is available, the answer is composed through the OpenAI Responses API with an evidence-only prompt.
- If no key is available, the app falls back to the closest cited evidence instead of pretending it knows more than the PDFs support.

## Important constraint

The public Vercel deployment is intentionally split into a static frontend plus a thin answer API. That means public visitors cannot persist new uploads directly into the repo, and the raw PDF library is not deployed with the site. The supported flow is:

1. Run the app locally
2. Add missing books
3. Commit and push the updated repo library
4. Everyone else sees the new sources through the shared link
