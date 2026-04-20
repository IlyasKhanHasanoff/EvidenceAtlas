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
const uploadForm = document.querySelector("#upload-form");
const uploadStatus = document.querySelector("#upload-status");
const jobList = document.querySelector("#job-list");
const uploadList = document.querySelector("#upload-list");
const resultTemplate = document.querySelector("#result-template");
const uploadTemplate = document.querySelector("#upload-template");
const jobTemplate = document.querySelector("#job-template");

const exampleQuery = "What evidence is there about sanitation reform in industrial cities?";
let pollHandle = null;

const escapeHtml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

const renderStats = (payload) => {
  stats.innerHTML = "";

  [
    { value: payload.excerptCount, label: "Indexed excerpts" },
    { value: payload.sourceCount, label: "Sources" },
    { value: payload.subjectCount, label: "Subject tags" },
    { value: payload.pendingOcrCount, label: "Need OCR" }
  ].forEach((item) => {
    const card = document.createElement("div");
    card.className = "stat-card";
    card.innerHTML = `<strong>${item.value}</strong><span>${item.label}</span>`;
    stats.append(card);
  });

  const semanticCard = document.createElement("div");
  semanticCard.className = "stat-card";
  semanticCard.innerHTML = `<strong>${payload.semanticEnabled ? "On" : "Off"}</strong><span>Semantic rerank</span>`;
  stats.append(semanticCard);
};

const renderSubjects = (subjects) => {
  const currentValue = subjectFilter.value;
  const options = [
    '<option value="">All indexed subjects</option>',
    ...subjects.map((subject) => `<option value="${escapeHtml(subject)}">${escapeHtml(subject)}</option>`)
  ];

  subjectFilter.innerHTML = options.join("");

  if (subjects.includes(currentValue)) {
    subjectFilter.value = currentValue;
  }
};

const renderSources = (sources) => {
  const currentValue = sourceFilter.value;
  const options = [
    '<option value="">All indexed sources</option>',
    ...sources.map(
      (source) =>
        `<option value="${escapeHtml(source.sourceId)}">${escapeHtml(source.title)} (${escapeHtml(source.author)})</option>`
    )
  ];

  sourceFilter.innerHTML = options.join("");

  if (sources.some((source) => source.sourceId === currentValue)) {
    sourceFilter.value = currentValue;
  }
};

const renderAnalysis = (analysis) => {
  analysisSummary.innerHTML = "";

  if (!analysis) {
    return;
  }

  const card = document.createElement("div");
  card.className = "analysis-card";
  card.innerHTML = `
    <strong>Question analysis mode: ${escapeHtml(analysis.mode)}</strong>
    <div class="analysis-chip-row" id="analysis-exact"></div>
    <div class="analysis-chip-row" id="analysis-concepts"></div>
    <div class="analysis-chip-row" id="analysis-expanded"></div>
  `;

  const exactRow = card.querySelector("#analysis-exact");
  const conceptRow = card.querySelector("#analysis-concepts");
  const expandedRow = card.querySelector("#analysis-expanded");

  if (analysis.exactPhrases.length) {
    exactRow.innerHTML = analysis.exactPhrases
      .map((phrase) => `<span class="analysis-chip">Exact: "${escapeHtml(phrase)}"</span>`)
      .join("");
  }

  conceptRow.innerHTML = analysis.conceptPhrases
    .slice(0, 5)
    .map((phrase) => `<span class="analysis-chip">Concept: ${escapeHtml(phrase)}</span>`)
    .join("");

  expandedRow.innerHTML = analysis.focusTerms
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
    renderEmptyState(
      "No evidence matched the analyzed question yet. Try broadening the question, removing a source filter, or using fewer quoted phrases."
    );
    return;
  }

  matches.forEach((match) => {
    const fragment = resultTemplate.content.cloneNode(true);
    fragment.querySelector(".subject-pill").textContent = match.subject;
    fragment.querySelector(".phrase-pill").textContent = match.exactPhraseMatch ? "Quoted phrase hit" : "Contextual match";
    fragment.querySelector(".concept-pill").textContent =
      match.conceptHits.length ? `${match.conceptHits.length} concept hits` : "Question analysis";
    fragment.querySelector(".score-pill").textContent =
      match.semanticSimilarity !== null && match.semanticSimilarity !== undefined
        ? `${match.semanticSimilarity.toFixed(3)} semantic`
        : `${match.score} heuristic`;
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

    results.append(fragment);
  });
};

const renderJobs = (jobs) => {
  jobList.innerHTML = "";

  jobs.slice(0, 6).forEach((job) => {
    const fragment = jobTemplate.content.cloneNode(true);
    fragment.querySelector(".job-name").textContent = job.filename;
    fragment.querySelector(".job-summary").textContent =
      job.pageCount
        ? `${job.pagesProcessed}/${job.pageCount} pages processed | ${job.excerptCount} excerpts`
        : "Waiting to start processing";
    fragment.querySelector(".job-status-line").textContent =
      job.status === "failed"
        ? `Status: failed | ${job.error}`
        : `Status: ${job.status} | ${job.ingestionStatus}`;
    jobList.append(fragment);
  });
};

const renderUploads = (sources) => {
  uploadList.innerHTML = "";

  sources.slice(0, 6).forEach((source) => {
    const fragment = uploadTemplate.content.cloneNode(true);
    fragment.querySelector(".upload-name").textContent = source.title;
    fragment.querySelector(".upload-summary").textContent =
      `${source.excerptCount} excerpts indexed | ${source.subject}`;
    fragment.querySelector(".upload-status-line").textContent =
      source.ingestionStatus === "needs_ocr"
        ? `Status: needs OCR | ${source.originalFilename || "uploaded source"}`
        : `Status: ${source.ingestionStatus} | ${source.originalFilename || "seeded source"}`;
    uploadList.append(fragment);
  });
};

const refreshCollection = async () => {
  const [statsResponse, subjectsResponse, sourcesResponse, jobsResponse] = await Promise.all([
    fetch("/api/stats"),
    fetch("/api/subjects"),
    fetch("/api/sources"),
    fetch("/api/jobs")
  ]);

  const statsPayload = await statsResponse.json();
  const subjectsPayload = await subjectsResponse.json();
  const sourcesPayload = await sourcesResponse.json();
  const jobsPayload = await jobsResponse.json();

  renderStats(statsPayload);
  renderSubjects(subjectsPayload.subjects);
  renderSources(sourcesPayload.sources);
  renderJobs(jobsPayload.jobs);
  renderUploads(sourcesPayload.sources);

  const activeJobs = jobsPayload.jobs.some((job) => job.status === "queued" || job.status === "processing");
  if (activeJobs && !pollHandle) {
    pollHandle = setInterval(() => {
      refreshCollection().catch(() => {});
    }, 3000);
  }
  if (!activeJobs && pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
};

const searchEvidence = async () => {
  const query = queryInput.value.trim();

  if (!query) {
    statusMessage.textContent = "Enter a question or subject first. The system only searches indexed excerpt records.";
    renderEmptyState("No search has been run yet.");
    return;
  }

  const params = new URLSearchParams({
    q: query,
    subject: subjectFilter.value,
    sourceId: sourceFilter.value
  });

  const response = await fetch(`/api/search?${params.toString()}`);
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || "Search failed.");
  }

  renderAnalysis(payload.analysis);
  statusMessage.textContent = payload.analysis.exactPhrases.length
    ? "Search completed with quoted exact-phrase constraints plus question analysis."
    : "Search completed with question analysis. If OpenAI embeddings are configured, semantic reranking is also applied.";
  renderResults(payload.results);
};

const handleUpload = async (event) => {
  event.preventDefault();

  const formData = new FormData(uploadForm);
  const files = formData.getAll("pdfs").filter((file) => file && file.size > 0);

  if (!files.length) {
    uploadStatus.textContent = "Choose at least one PDF file first.";
    return;
  }

  uploadStatus.textContent = `Uploading ${files.length} PDF ${files.length === 1 ? "file" : "files"}...`;

  const response = await fetch("/api/upload", {
    method: "POST",
    body: formData
  });
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || "Upload failed.");
  }

  uploadStatus.textContent =
    `Upload accepted. ${payload.jobs.length} file${payload.jobs.length === 1 ? "" : "s"} queued for background processing. You can keep using the app while large books ingest.`;

  uploadForm.reset();
  renderStats(payload.stats);
  renderJobs(payload.jobs);
  await refreshCollection();
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

loadExampleButton.addEventListener("click", () => {
  queryInput.value = exampleQuery;
  queryInput.focus();
});

refreshCollection()
  .then(() => {
    renderEmptyState("The evidence database is ready. Ask a question to retrieve exact excerpts and citation metadata.");
  })
  .catch((error) => {
    statusMessage.textContent = error.message;
    renderEmptyState("The evidence database could not be loaded.");
  });
