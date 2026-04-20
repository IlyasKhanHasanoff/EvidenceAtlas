const queryInput = document.querySelector("#query");
const subjectFilter = document.querySelector("#subject-filter");
const sourceFilter = document.querySelector("#source-filter");
const statusMessage = document.querySelector("#status-message");
const stats = document.querySelector("#stats");
const analysisSummary = document.querySelector("#analysis-summary");
const results = document.querySelector("#results");
const resultCount = document.querySelector("#result-count");
const searchForm = document.querySelector("#search-form");
const loadExampleButton = document.querySelector("#load-example");
const uploadPanel = document.querySelector("#upload-panel");
const uploadModeMessage = document.querySelector("#upload-mode-message");
const uploadForm = document.querySelector("#upload-form");
const inboxForm = document.querySelector("#inbox-form");
const uploadStatus = document.querySelector("#upload-status");
const inboxList = document.querySelector("#inbox-list");
const jobList = document.querySelector("#job-list");
const sourceList = document.querySelector("#source-list");
const resultTemplate = document.querySelector("#result-template");
const listCardTemplate = document.querySelector("#list-card-template");

const STOP_WORDS = new Set([
  "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "into", "is", "it",
  "of", "on", "or", "that", "the", "there", "this", "to", "was", "what", "when", "where", "which",
  "who", "why", "with", "evidence", "find", "about", "tell", "me"
]);

const RELATED_TERMS = {
  abolition: ["freedom", "slavery", "enslaved"],
  city: ["cities", "urban", "municipal"],
  disease: ["illness", "mortality", "health"],
  education: ["school", "schools", "learning"],
  factory: ["industrial", "industry", "manufacturing"],
  food: ["meat", "inspection", "packing"],
  housing: ["tenement", "tenements", "slum", "slums"],
  industrial: ["factory", "factories", "industry", "manufacturing"],
  inspection: ["inspectors", "oversight", "regulation"],
  law: ["legal", "statute", "legislation"],
  poverty: ["poor", "slum", "slums", "tenement"],
  public: ["municipal", "civic"],
  reform: ["reforms", "improvement", "improvements", "change", "inspection", "administration"],
  sanitary: ["sanitation", "drainage", "sewer", "sewers", "filth", "water"],
  sanitation: ["sanitary", "drainage", "sewer", "sewers", "filth", "water", "ventilation"],
  slavery: ["enslaved", "abolition", "freedom"],
  urban: ["city", "cities", "municipal"],
  water: ["drainage", "sewer", "sewers"]
};

let library = { sources: [], records: [] };
let pollHandle = null;
let localMode = false;

const exampleQuery = "What evidence is there about sanitation reform in industrial cities?";

const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

const tokenize = (text) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((token) => token && !STOP_WORDS.has(token));

const unique = (values) => [...new Set(values)].sort((left, right) => left.localeCompare(right));

const normalizeTerm = (term) => {
  if (term.length > 5 && term.endsWith("ies")) return `${term.slice(0, -3)}y`;
  if (term.length > 4 && term.endsWith("ing")) return term.slice(0, -3);
  if (term.length > 3 && term.endsWith("ed")) return term.slice(0, -2);
  if (term.length > 4 && term.endsWith("es")) return term.slice(0, -2);
  if (term.length > 3 && term.endsWith("s")) return term.slice(0, -1);
  return term;
};

const buildConceptPhrases = (tokens) => {
  const phrases = [];
  [3, 2].forEach((size) => {
    for (let index = 0; index <= tokens.length - size; index += 1) {
      const phrase = tokens.slice(index, index + size).join(" ");
      if (!phrases.includes(phrase)) {
        phrases.push(phrase);
      }
    }
  });
  return phrases.slice(0, 6);
};

const analyzeQuestion = (query) => {
  const exactPhrases = [...query.matchAll(/"([^"]+)"/g)].map((match) => match[1].trim()).filter(Boolean);
  const unquoted = query.replace(/"[^"]+"/g, " ");
  const rawTokens = tokenize(unquoted);
  const focusTerms = unique(rawTokens.map(normalizeTerm).filter((token) => token.length > 2)).slice(0, 10);
  const conceptPhrases = buildConceptPhrases(rawTokens);
  const expandedTerms = new Set(focusTerms);

  focusTerms.forEach((term) => {
    (RELATED_TERMS[term] || []).forEach((related) => expandedTerms.add(related));
  });

  return {
    originalQuery: query,
    exactPhrases,
    focusTerms,
    conceptPhrases,
    expandedTerms: [...expandedTerms].slice(0, 24),
    mode: exactPhrases.length ? "quoted-exact" : "analyzed"
  };
};

const tokenPositions = (tokens) => {
  const positions = {};
  tokens.forEach((token, index) => {
    const normalized = normalizeTerm(token);
    positions[normalized] ??= [];
    positions[normalized].push(index);
  });
  return positions;
};

const conceptPresent = (phrase, positionsMap, window = 10) => {
  const terms = tokenize(phrase).map(normalizeTerm);
  if (!terms.length || terms.some((term) => !positionsMap[term])) return false;

  return positionsMap[terms[0]].some((anchor) =>
    terms.slice(1).every((term) => positionsMap[term].some((position) => Math.abs(position - anchor) <= window))
  );
};

const scoreRecord = (record, analysis) => {
  const fullText = [record.title, record.author, record.subject, record.excerpt, ...(record.keywords || [])].join(" ");
  const rawTokens = (fullText.toLowerCase().match(/[a-z0-9]+/g) || []);
  const normalizedTokens = rawTokens.map(normalizeTerm);
  const normalizedSet = new Set(normalizedTokens);
  const positionsMap = tokenPositions(rawTokens);

  const exactPhraseHits = analysis.exactPhrases.filter((phrase) => {
    const lowered = phrase.toLowerCase();
    return record.excerpt.toLowerCase().includes(lowered) || record.title.toLowerCase().includes(lowered);
  });

  if (analysis.exactPhrases.length && exactPhraseHits.length !== analysis.exactPhrases.length) {
    return null;
  }

  const focusHits = analysis.focusTerms.filter((term) => normalizedSet.has(term));
  const expandedHits = analysis.expandedTerms.filter((term) => normalizedSet.has(term) && !focusHits.includes(term));
  const conceptHits = analysis.conceptPhrases.filter((phrase) => conceptPresent(phrase, positionsMap));
  const titleText = `${record.title} ${record.author} ${record.subject}`.toLowerCase();
  const titleFocusHits = analysis.focusTerms.filter((term) => titleText.includes(term));

  let score = 0;
  score += exactPhraseHits.length * 120;
  score += conceptHits.length * 22;
  score += focusHits.length * 8;
  score += expandedHits.slice(0, 6).length * 3;
  score += titleFocusHits.length * 10;

  if (score <= 0) return null;

  const matches = unique([
    ...exactPhraseHits.map((phrase) => `"${phrase}"`),
    ...conceptHits.slice(0, 4),
    ...focusHits.slice(0, 6),
    ...expandedHits.slice(0, 4)
  ]);

  return {
    ...record,
    score,
    exactPhraseMatch: exactPhraseHits.length > 0,
    conceptHits,
    focusHits,
    matches
  };
};

const renderStats = () => {
  stats.innerHTML = "";

  const values = [
    { value: library.records.length, label: "Indexed excerpts" },
    { value: library.sources.length, label: "Sources" },
    { value: unique(library.records.map((record) => record.subject)).length, label: "Subjects" },
    { value: library.sources.filter((source) => source.ingestionStatus === "needs_ocr").length, label: "Need OCR" }
  ];

  values.forEach((item) => {
    const card = document.createElement("div");
    card.className = "stat-card";
    card.innerHTML = `<strong>${item.value}</strong><span>${item.label}</span>`;
    stats.append(card);
  });
};

const renderSubjects = () => {
  const currentValue = subjectFilter.value;
  const subjects = unique(library.records.map((record) => record.subject));
  subjectFilter.innerHTML = [
    '<option value="">All subjects</option>',
    ...subjects.map((subject) => `<option value="${escapeHtml(subject)}">${escapeHtml(subject)}</option>`)
  ].join("");
  if (subjects.includes(currentValue)) {
    subjectFilter.value = currentValue;
  }
};

const renderSources = () => {
  const currentValue = sourceFilter.value;
  sourceFilter.innerHTML = [
    '<option value="">All sources</option>',
    ...library.sources.map(
      (source) =>
        `<option value="${escapeHtml(source.sourceId)}">${escapeHtml(source.title)} (${escapeHtml(source.author)})</option>`
    )
  ].join("");
  if (library.sources.some((source) => source.sourceId === currentValue)) {
    sourceFilter.value = currentValue;
  }
};

const renderAnalysis = (analysis) => {
  analysisSummary.innerHTML = "";
  const card = document.createElement("div");
  card.className = "analysis-card";
  card.innerHTML = `
    <strong>Question analysis mode: ${escapeHtml(analysis.mode)}</strong>
    <div class="analysis-chip-row"></div>
    <div class="analysis-chip-row"></div>
    <div class="analysis-chip-row"></div>
  `;
  const rows = card.querySelectorAll(".analysis-chip-row");

  rows[0].innerHTML = analysis.exactPhrases
    .map((phrase) => `<span class="analysis-chip">Exact: "${escapeHtml(phrase)}"</span>`)
    .join("");
  rows[1].innerHTML = analysis.conceptPhrases
    .slice(0, 5)
    .map((phrase) => `<span class="analysis-chip">Concept: ${escapeHtml(phrase)}</span>`)
    .join("");
  rows[2].innerHTML = analysis.focusTerms
    .slice(0, 8)
    .map((term) => `<span class="analysis-chip">Focus: ${escapeHtml(term)}</span>`)
    .join("");

  analysisSummary.append(card);
};

const renderEmptyState = (message) => {
  results.innerHTML = `<div class="empty-state">${message}</div>`;
  resultCount.textContent = "0 matches";
};

const renderResults = (matches) => {
  results.innerHTML = "";
  resultCount.textContent = `${matches.length} ${matches.length === 1 ? "match" : "matches"}`;

  if (!matches.length) {
    renderEmptyState("No evidence matched the analyzed question yet. Try broadening the question or removing a source filter.");
    return;
  }

  matches.forEach((match) => {
    const fragment = resultTemplate.content.cloneNode(true);
    fragment.querySelector(".subject-pill").textContent = match.subject;
    fragment.querySelector(".phrase-pill").textContent = match.exactPhraseMatch ? "Quoted phrase hit" : "Contextual match";
    fragment.querySelector(".concept-pill").textContent =
      match.conceptHits.length ? `${match.conceptHits.length} concept hits` : "Question analysis";
    fragment.querySelector(".score-pill").textContent = `${match.score} relevance`;
    fragment.querySelector(".result-title").textContent = match.title;
    fragment.querySelector(".result-meta").textContent =
      `${match.author} | ${match.year} | Page ${match.page} | ${match.sourceId}`;
    fragment.querySelector(".excerpt").textContent = `"${match.excerpt}"`;

    const tags = fragment.querySelector(".match-tags");
    match.matches.forEach((term) => {
      const chip = document.createElement("span");
      chip.className = "match-tag";
      chip.textContent = term;
      tags.append(chip);
    });

    const link = fragment.querySelector(".result-link");
    if (match.pdfPath) {
      link.innerHTML = `<a href="${escapeHtml(match.pdfPath)}" target="_blank" rel="noreferrer">Open source PDF</a>`;
    }

    results.append(fragment);
  });
};

const renderJobs = (jobs) => {
  jobList.innerHTML = "";
  jobs.slice(0, 6).forEach((job) => {
    const fragment = listCardTemplate.content.cloneNode(true);
    fragment.querySelector(".item-name").textContent = job.filename;
    fragment.querySelector(".item-summary").textContent =
      job.pageCount
        ? `${job.pagesProcessed}/${job.pageCount} pages processed | ${job.excerptCount} excerpts`
        : "Waiting to start processing";
    fragment.querySelector(".item-detail").textContent =
      job.status === "failed" ? `Status: failed | ${job.error}` : `Status: ${job.status} | ${job.ingestionStatus}`;
    jobList.append(fragment);
  });
};

const renderInbox = (files) => {
  inboxList.innerHTML = "";
  if (!files.length) {
    inboxList.innerHTML = '<div class="empty-state">The local inbox is empty. Copy large PDFs into <code>library-inbox/</code> to import them.</div>';
    return;
  }

  files.slice(0, 8).forEach((file) => {
    const fragment = listCardTemplate.content.cloneNode(true);
    fragment.querySelector(".item-name").textContent = file.filename;
    fragment.querySelector(".item-summary").textContent =
      `${Math.max(1, Math.round(file.size / 1024 / 1024))} MB | waiting in inbox`;
    fragment.querySelector(".item-detail").textContent = "Ready to import into the shared repo library";
    inboxList.append(fragment);
  });
};

const renderSourceList = () => {
  sourceList.innerHTML = "";
  library.sources.slice(0, 6).forEach((source) => {
    const fragment = listCardTemplate.content.cloneNode(true);
    fragment.querySelector(".item-name").textContent = source.title;
    fragment.querySelector(".item-summary").textContent = `${source.excerptCount} excerpts | ${source.subject}`;
    fragment.querySelector(".item-detail").textContent =
      source.pdfPath ? `Saved in repo | ${source.ingestionStatus}` : `Repo seed | ${source.ingestionStatus}`;
    sourceList.append(fragment);
  });
};

const fetchLibrary = async () => {
  const response = await fetch("./library/index.json", { cache: "no-store" });
  if (!response.ok) throw new Error("The repo library index could not be loaded.");
  library = await response.json();
  renderStats();
  renderSubjects();
  renderSources();
  renderSourceList();
};

const searchEvidence = async () => {
  const query = queryInput.value.trim();
  if (!query) {
    statusMessage.textContent = "Enter a question first. The app only searches the committed library index.";
    renderEmptyState("No search has been run yet.");
    return;
  }

  const analysis = analyzeQuestion(query);
  renderAnalysis(analysis);

  const matches = library.records
    .filter((record) => !subjectFilter.value || record.subject === subjectFilter.value)
    .filter((record) => !sourceFilter.value || record.sourceRef === sourceFilter.value)
    .map((record) => scoreRecord(record, analysis))
    .filter(Boolean)
    .sort((left, right) => right.score - left.score || left.page - right.page)
    .slice(0, 50);

  statusMessage.textContent = analysis.exactPhrases.length
    ? "Search completed with quoted exact constraints against the shared repo library."
    : "Search completed against the shared repo library using question analysis and contextual ranking.";
  renderResults(matches);
};

const refreshJobs = async () => {
  if (!localMode) return;

  const response = await fetch("/api/jobs");
  const payload = await response.json();
  renderJobs(payload.jobs);

  const activeJobs = payload.jobs.some((job) => job.status === "queued" || job.status === "processing");
  if (activeJobs && !pollHandle) {
    pollHandle = setInterval(() => {
      Promise.all([refreshJobs(), fetchLibrary()]).catch(() => {});
    }, 3000);
  }
  if (!activeJobs && pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
};

const refreshInbox = async () => {
  if (!localMode) return;
  const response = await fetch("/api/inbox", { cache: "no-store" });
  const payload = await response.json();
  renderInbox(payload.files || []);
};

const detectLocalMode = async () => {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    localMode = payload.ok === true;
  } catch {
    localMode = false;
  }

  if (localMode) {
    uploadForm.classList.remove("hidden");
    inboxForm.classList.remove("hidden");
    uploadModeMessage.textContent =
      "Local mode is active. Small PDFs can upload here, and large books can be copied into library-inbox/ and imported into the repo library.";
  } else {
    uploadForm.classList.add("hidden");
    inboxForm.classList.add("hidden");
    uploadModeMessage.textContent =
      "Shared GitHub mode is read-only. Run locally if you need to add books into the repo library.";
  }
};

const handleUpload = async (event) => {
  event.preventDefault();
  const formData = new FormData(uploadForm);
  const files = formData.getAll("pdfs").filter((file) => file && file.size > 0);

  if (!files.length) {
    uploadStatus.textContent = "Choose at least one PDF file first.";
    return;
  }

  uploadStatus.textContent = `Copying ${files.length} PDF ${files.length === 1 ? "file" : "files"} into the repo library...`;

  const response = await fetch("/api/upload", {
    method: "POST",
    body: formData
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Upload failed.");
  }

  const skipped = payload.skipped?.length ? ` Skipped duplicates: ${payload.skipped.join(", ")}.` : "";
  uploadStatus.textContent = `${payload.message}${skipped}`;
  uploadForm.reset();
  renderJobs(payload.jobs);
  await Promise.all([fetchLibrary(), refreshJobs(), refreshInbox()]);
};

const handleInboxImport = async (event) => {
  event.preventDefault();
  uploadStatus.textContent = "Importing PDFs from library-inbox into the shared repo library...";

  const response = await fetch("/api/import-inbox", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({})
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Inbox import failed.");
  }

  const skipped = payload.skipped?.length ? ` Skipped duplicates: ${payload.skipped.join(", ")}.` : "";
  uploadStatus.textContent = `${payload.message}${skipped}`;
  renderJobs(payload.jobs || []);
  await Promise.all([fetchLibrary(), refreshJobs(), refreshInbox()]);
};

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  searchEvidence().catch((error) => {
    statusMessage.textContent = error.message;
  });
});

uploadForm.addEventListener("submit", (event) => {
  handleUpload(event).catch((error) => {
    uploadStatus.textContent = error.message;
  });
});

inboxForm.addEventListener("submit", (event) => {
  handleInboxImport(event).catch((error) => {
    uploadStatus.textContent = error.message;
  });
});

loadExampleButton.addEventListener("click", () => {
  queryInput.value = exampleQuery;
  queryInput.focus();
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./service-worker.js").catch(() => {});
  });
}

Promise.all([detectLocalMode(), fetchLibrary()])
  .then(() => {
    renderEmptyState("The shared repo library is ready. Ask a question to retrieve exact excerpts and citations.");
    return Promise.all([refreshJobs(), refreshInbox()]);
  })
  .catch((error) => {
    statusMessage.textContent = error.message;
    renderEmptyState("The shared repo library could not be loaded.");
  });
