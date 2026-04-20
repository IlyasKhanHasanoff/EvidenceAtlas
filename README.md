# Evidence Atlas

Evidence Atlas is now a repo-backed app rather than only a local website. The same committed library files power:

- local app mode, where you can add new PDFs into the repo
- GitHub Pages mode, where anyone with the link can open and search the shared library without uploading anything

## Core model

- Shared library data lives in [docs/library/index.json](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\library\index.json)
- Shared PDFs live in [docs/library/pdfs](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\library\pdfs)
- Large local import staging lives in [library-inbox](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\library-inbox)
- Developer-shared PDF staging lives in [repo-pdf-drop](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\repo-pdf-drop)
- The app UI lives in [docs/index.html](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\index.html), [docs/app.js](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\app.js), and [docs/styles.css](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\docs\styles.css)
- Local mode uses [server.py](C:\Users\hasan\Documents\Codex\2026-04-20-build-a-website-that-will-only\server.py) only to add books into that repo library and serve the app locally

## What changed

- Search is now client-side against the committed library index, so GitHub Pages can serve it.
- Anyone with the app link can open the shared library immediately with no upload step.
- Local uploads are copied into the repo library folder so they become part of the shared project content.
- Large PDFs can be dropped into `library-inbox/` and imported without pushing the whole file through the browser.
- Shared developer PDFs can be committed into `repo-pdf-drop/` and imported into the library without removing them from that repo folder.
- Quoted words or phrases are treated as exact constraints; everything else uses question-analysis-based retrieval.
- Subjects and optional sub-subjects can be assigned during ingestion, and search can stay at the subject level or narrow to one sub-subject.
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

## Use on GitHub

Set GitHub Pages to publish from the `docs/` folder on `main`.

Once that is enabled:

- the app loads from `docs/`
- the shared library loads from `docs/library/index.json`
- committed PDFs in `docs/library/pdfs/` are available to every visitor

## Use on Vercel

This repo is also ready for Vercel:

- the shared app is served from `docs/`
- `/api/health` stays read-only on Vercel so the UI does not expose local-only upload behavior
- `/api/answer` can produce evidence-grounded answers on Vercel too if `OPENAI_API_KEY` is configured in the Vercel project environment
- local ingestion still happens through `server.py` when you run the project on your own machine

## Upload behavior

- In local mode, the upload panel is enabled.
- Browser uploads copy PDFs into `docs/library/pdfs/`.
- Large books can be copied into `library-inbox/` first, then imported from the app with one button.
- Developers can also commit PDFs into `repo-pdf-drop/`, push them, and import them from the app with one button.
- A background job extracts excerpts and updates `docs/library/index.json`.
- Each source can carry a subject plus an optional sub-subject.
- Duplicate original filenames are skipped so the same book is not imported repeatedly.
- After that, commit and push the changed library files so GitHub visitors get the new books too.

## Answering behavior

- The answer panel uses only the retrieved library evidence for the current question.
- It returns a short answer plus page citations to the excerpts it used.
- If `OPENAI_API_KEY` is available, the answer is composed through the OpenAI Responses API with an evidence-only prompt.
- If no key is available, the app falls back to the closest cited evidence instead of pretending it knows more than the PDFs support.

## Important constraint

GitHub Pages is static. That means public visitors cannot persist new uploads directly into the repo without an authenticated backend workflow. The supported flow is:

1. Run the app locally
2. Add missing books
3. Commit and push the updated repo library
4. Everyone else sees the new sources through the shared link
