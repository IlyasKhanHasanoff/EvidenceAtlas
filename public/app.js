const queryInput = document.querySelector("#query");
const subjectFilter = document.querySelector("#subject-filter");
const minScoreInput = document.querySelector("#min-score");
const minScoreLabel = document.querySelector("#min-score-label");
const statusMessage = document.querySelector("#status-message");
const stats = document.querySelector("#stats");
const results = document.querySelector("#results");
const resultCount = document.querySelector("#result-count");
const searchForm = document.querySelector("#search-form");
const loadExampleButton = document.querySelector("#load-example");
const uploadForm = document.querySelector("#upload-form");
const uploadStatus = document.querySelector("#upload-status");
const uploadList = document.querySelector("#upload-list");
const resultTemplate = document.querySelector("#result-template");
const uploadTemplate = document.querySelector("#upload-template");

const exampleQuery = "What evidence is there about sanitation reform in industrial cities?";

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

const renderEmptyState = (message) => {
  results.innerHTML = `<div class="empty-state">${message}</div>`;
  resultCount.textContent = "0 matches";
};

const renderResults = (matches) => {
  results.innerHTML = "";
  resultCount.textContent = `${matches.length} ${matches.length === 1 ? "match" : "matches"}`;

  if (!matches.length) {
    renderEmptyState(
      "No excerpt met the current threshold. Try a broader query, lower the matching-terms slider, or remove the subject filter."
    );
    return;
  }

  matches.forEach((match) => {
    const fragment = resultTemplate.content.cloneNode(true);
    fragment.querySelector(".subject-pill").textContent = match.subject;
    fragment.querySelector(".score-pill").textContent = `${match.matchCount} matched terms`;
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
  const [statsResponse, subjectsResponse, sourcesResponse] = await Promise.all([
    fetch("/api/stats"),
    fetch("/api/subjects"),
    fetch("/api/sources")
  ]);

  const statsPayload = await statsResponse.json();
  const subjectsPayload = await subjectsResponse.json();
  const sourcesPayload = await sourcesResponse.json();

  renderStats(statsPayload);
  renderSubjects(subjectsPayload.subjects);
  renderUploads(sourcesPayload.sources);
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
    minTerms: minScoreInput.value
  });

  const response = await fetch(`/api/search?${params.toString()}`);
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || "Search failed.");
  }

  statusMessage.textContent =
    "Search completed across the persistent evidence database. Results show exact citations only; no synthesized answer is produced.";
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

  const indexedCount = payload.uploaded.reduce((sum, item) => sum + item.excerptCount, 0);
  const ocrCount = payload.uploaded.filter((item) => item.ingestionStatus === "needs_ocr").length;
  uploadStatus.textContent =
    ocrCount > 0
      ? `Upload complete. Added ${indexedCount} excerpts. ${ocrCount} source${ocrCount === 1 ? "" : "s"} still need OCR.`
      : `Upload complete. Added ${indexedCount} excerpts to the persistent evidence database.`;

  uploadForm.reset();
  renderStats(payload.stats);
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

minScoreInput.addEventListener("input", () => {
  const value = Number(minScoreInput.value);
  minScoreLabel.textContent = `${value} matching ${value === 1 ? "term" : "terms"}`;
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
