const queryInput = document.querySelector("#query");
const topicSearch = document.querySelector("#topic-search");
const topicFilter = document.querySelector("#topic-filter");
const subjectSearch = document.querySelector("#subject-search");
const subjectFilter = document.querySelector("#subject-filter");
const sourceFilter = document.querySelector("#source-filter");
const statusMessage = document.querySelector("#status-message");
const stats = document.querySelector("#stats");
const analysisSummary = document.querySelector("#analysis-summary");
const answerStatus = document.querySelector("#answer-status");
const answerCard = document.querySelector("#answer-card");
const answerCitations = document.querySelector("#answer-citations");
const results = document.querySelector("#results");
const resultCount = document.querySelector("#result-count");
const searchForm = document.querySelector("#search-form");
const loadExampleButton = document.querySelector("#load-example");
const uploadPanel = document.querySelector("#upload-panel");
const uploadModeMessage = document.querySelector("#upload-mode-message");
const uploadForm = document.querySelector("#upload-form");
const inboxForm = document.querySelector("#inbox-form");
const repoDropForm = document.querySelector("#repo-drop-form");
const libraryPdfForm = document.querySelector("#library-pdf-form");
const blobSyncForm = document.querySelector("#blob-sync-form");
const uploadStatus = document.querySelector("#upload-status");
const libraryPdfList = document.querySelector("#library-pdf-list");
const inboxList = document.querySelector("#inbox-list");
const repoDropList = document.querySelector("#repo-drop-list");
const jobList = document.querySelector("#job-list");
const sourceList = document.querySelector("#source-list");
const resultTemplate = document.querySelector("#result-template");
const listCardTemplate = document.querySelector("#list-card-template");
const citationTemplate = document.querySelector("#citation-template");

const STOP_WORDS = new Set([
  "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "into", "is", "it",
  "of", "on", "or", "that", "the", "there", "this", "to", "was", "what", "when", "where", "which",
  "who", "why", "with", "evidence", "find", "about", "tell", "me", "i", "should", "say", "says",
  "said", "saying", "would", "could", "can"
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

const exampleQuery = "What should a person say when hearing the adhan?";

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
const normalizeOptionalText = (value) => (value || "").trim();
const canOpenPdf = (pdfPath) => Boolean(pdfPath) && (localMode || /^https?:\/\//i.test(pdfPath));

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
  const lowered = query.toLowerCase();
  const exactPhrases = [...query.matchAll(/"([^"]+)"/g)].map((match) => match[1].trim()).filter(Boolean);
  const unquoted = query.replace(/"[^"]+"/g, " ");
  const rawTokens = tokenize(unquoted);
  const focusTerms = unique(rawTokens.map(normalizeTerm).filter((token) => token.length > 2)).slice(0, 10);
  const conceptPhrases = buildConceptPhrases(rawTokens);
  const expandedTerms = new Set(focusTerms);

  focusTerms.forEach((term) => {
    (RELATED_TERMS[term] || []).forEach((related) => expandedTerms.add(related));
  });

  const intentTerms = [];
  if (/\b(say|recite|repeat|words?)\b/.test(lowered)) {
    intentTerms.push("say", "repeat", "recite", "words", "hear");
  }
  if (/\b(where|from)\b/.test(lowered)) {
    intentTerms.push("from", "born", "place", "city");
  }

  return {
    originalQuery: query,
    exactPhrases,
    focusTerms,
    conceptPhrases,
    expandedTerms: [...expandedTerms].slice(0, 24),
    intentTerms: unique(intentTerms),
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
  const fullText = [record.title, record.author, record.topic || "", record.subject || "", record.excerpt, ...(record.keywords || [])].join(" ");
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
  const intentHits = (analysis.intentTerms || []).filter((term) => normalizedSet.has(term));
  const conceptHits = analysis.conceptPhrases.filter((phrase) => conceptPresent(phrase, positionsMap));
  const titleText = `${record.title} ${record.author} ${record.topic || ""} ${record.subject || ""}`.toLowerCase();
  const titleFocusHits = analysis.focusTerms.filter((term) => titleText.includes(term));

  if (analysis.focusTerms.length && !(focusHits.length || exactPhraseHits.length || titleFocusHits.length)) {
    return null;
  }

  let score = 0;
  score += exactPhraseHits.length * 120;
  score += conceptHits.length * 22;
  score += focusHits.length * 8;
  score += expandedHits.slice(0, 6).length * 3;
  score += intentHits.length * 10;
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
    intentHits,
    matches
  };
};

const renderStats = () => {
  stats.innerHTML = "";

  const values = [
    { value: library.records.length, label: "Indexed excerpts" },
    { value: library.sources.length, label: "Sources" },
    { value: unique(library.records.map((record) => record.topic).filter(Boolean)).length, label: "Topics" },
    { value: unique(library.records.map((record) => record.subject).filter(Boolean)).length, label: "Subjects" },
    { value: library.sources.filter((source) => source.ingestionStatus === "needs_ocr").length, label: "Need OCR" }
  ];

  values.forEach((item) => {
    const card = document.createElement("div");
    card.className = "stat-card";
    card.innerHTML = `<strong>${item.value}</strong><span>${item.label}</span>`;
    stats.append(card);
  });
};

const filterBySearch = (values, searchText) => {
  const needle = searchText.trim().toLowerCase();
  if (!needle) return values;
  return values.filter((value) => value.toLowerCase().includes(needle));
};

const renderTopics = () => {
  const currentValue = topicFilter.value;
  const topics = filterBySearch(
    unique(library.sources.map((source) => source.topic).filter(Boolean)),
    topicSearch.value
  );
  topicFilter.innerHTML = [
    '<option value="">All topics</option>',
    ...topics.map((topic) => `<option value="${escapeHtml(topic)}">${escapeHtml(topic)}</option>`)
  ].join("");
  if (topics.includes(currentValue)) {
    topicFilter.value = currentValue;
  } else {
    topicFilter.value = "";
  }
};

const renderSubjects = () => {
  const currentValue = subjectFilter.value;
  const available = library.sources
    .filter((source) => !topicFilter.value || source.topic === topicFilter.value)
    .map((source) => normalizeOptionalText(source.subject))
    .filter(Boolean);
  const subjects = filterBySearch(unique(available), subjectSearch.value);

  subjectFilter.innerHTML = [
    '<option value="">All subjects</option>',
    ...subjects.map((subject) => `<option value="${escapeHtml(subject)}">${escapeHtml(subject)}</option>`)
  ].join("");

  if (subjects.includes(currentValue)) {
    subjectFilter.value = currentValue;
  } else {
    subjectFilter.value = "";
  }
};

const renderSources = () => {
  const currentValue = sourceFilter.value;
  const filteredSources = library.sources.filter(
    (source) =>
      (!topicFilter.value || source.topic === topicFilter.value) &&
      (!subjectFilter.value || normalizeOptionalText(source.subject) === subjectFilter.value)
  );
  sourceFilter.innerHTML = [
    '<option value="">All sources</option>',
    ...filteredSources.map(
      (source) =>
        `<option value="${escapeHtml(source.sourceId)}">${escapeHtml(source.title)} (${escapeHtml(source.author)})</option>`
    )
  ].join("");
  if (filteredSources.some((source) => source.sourceId === currentValue)) {
    sourceFilter.value = currentValue;
  } else {
    sourceFilter.value = "";
  }
};

const renderAnalysis = (analysis) => {
  analysisSummary.innerHTML = "";
  const card = document.createElement("div");
  card.className = "analysis-card";
  card.innerHTML = `
    <strong>Prompt mode: ${escapeHtml(analysis.promptMode || analysis.mode)}</strong>
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

const renderAnswer = (payload) => {
  const assessmentMap = {
    "mostly-supported": "Mostly supported",
    "mostly-opposed": "Mostly opposed",
    mixed: "Mixed evidence",
    insufficient: "Insufficient evidence"
  };
  answerStatus.textContent = payload.grounded
    ? (assessmentMap[payload.overallAssessment] || "Grounded response")
    : "Insufficient direct evidence";
  answerCard.innerHTML = `
    <strong>${escapeHtml(payload.grounded ? "Grounded response" : "Evidence status")}</strong>
    <p>${escapeHtml(payload.answer)}</p>
  `;

  answerCitations.innerHTML = "";
  const sections = [
    { label: "Evidence for", items: payload.supportingEvidence || [] },
    { label: "Evidence against", items: payload.opposingEvidence || [] },
    { label: "Most relevant passages", items: payload.usedCitations || [] }
  ].filter((section) => section.items.length);

  sections.forEach((section) => {
    const header = document.createElement("p");
    header.className = "match-label";
    header.textContent = section.label;
    answerCitations.append(header);

    section.items.forEach((citation) => {
      const fragment = citationTemplate.content.cloneNode(true);
      fragment.querySelector(".item-name").textContent = `[${citation.marker}] ${citation.title}`;
      fragment.querySelector(".item-summary").textContent =
        `${citation.author} | ${citation.year} | ${citation.subject ? `${citation.topic} / ${citation.subject}` : citation.topic} | Page ${citation.page}`;
      fragment.querySelector(".item-detail").textContent = `"${citation.excerpt}"`;
      answerCitations.append(fragment);
    });
  });
};

const renderFallbackAnswer = (matches) => {
  const supportingEvidence = matches
    .filter((match) => match.evidenceDirection === "support")
    .slice(0, 3)
    .map((match, index) => ({
      marker: index + 1,
      title: match.title,
      author: match.author,
      year: match.year,
      topic: match.topic,
      subject: match.subject,
      page: match.page,
      excerpt: match.excerpt
    }));
  const opposingEvidence = matches
    .filter((match) => match.evidenceDirection === "oppose")
    .slice(0, 3)
    .map((match, index) => ({
      marker: supportingEvidence.length + index + 1,
      title: match.title,
      author: match.author,
      year: match.year,
      topic: match.topic,
      subject: match.subject,
      page: match.page,
      excerpt: match.excerpt
    }));
  const usedCitations = [...supportingEvidence, ...opposingEvidence].slice(0, 4);

  renderAnswer({
    grounded: false,
    overallAssessment: usedCitations.length ? "mixed" : "insufficient",
    answer: usedCitations.length
      ? "The answer service is unavailable right now, but the closest supporting and opposing passages are shown below."
      : "The answer service is unavailable right now, and no strong passages were retrieved.",
    supportingEvidence,
    opposingEvidence,
    usedCitations
  });
};

const renderResults = (matches) => {
  results.innerHTML = "";
  resultCount.textContent = `${matches.length} ${matches.length === 1 ? "passage" : "passages"}`;

  if (!matches.length) {
    renderEmptyState("No relevant evidence was found yet. Try broadening the prompt or removing a source filter.");
    return;
  }

  matches.forEach((match) => {
    const fragment = citationTemplate.content.cloneNode(true);
    const directionLabel = match.evidenceDirection === "support"
      ? "Supports prompt"
      : match.evidenceDirection === "oppose"
        ? "Challenges prompt"
        : "Related evidence";
    const fragment = resultTemplate.content.cloneNode(true);
    fragment.querySelector(".subject-pill").textContent =
      match.subject ? `${match.topic} / ${match.subject}` : match.topic;
    fragment.querySelector(".phrase-pill").textContent = match.exactPhraseMatch ? "Quoted phrase hit" : directionLabel;
    fragment.querySelector(".concept-pill").textContent =
      match.conceptHits.length ? `${match.conceptHits.length} concept hits` : "Evidence analysis";
    fragment.querySelector(".score-pill").textContent = `${match.score} evidence score`;
    fragment.querySelector(".result-title").textContent = match.title;
    fragment.querySelector(".result-meta").textContent =
      `${match.author} | ${match.year} | ${match.subject ? `${match.subject} | ` : ""}Page ${match.page} | ${match.sourceId}`;
    fragment.querySelector(".excerpt").textContent = `"${match.excerpt}"`;

    const tags = fragment.querySelector(".match-tags");
    match.matches.forEach((term) => {
      const chip = document.createElement("span");
      chip.className = "match-tag";
      chip.textContent = term;
      tags.append(chip);
    });

    const link = fragment.querySelector(".result-link");
    if (canOpenPdf(match.pdfPath)) {
      link.innerHTML = `<a href="${escapeHtml(match.pdfPath)}" target="_blank" rel="noreferrer">Open source PDF</a>`;
    } else if (match.pdfPath) {
      link.textContent = "Source PDF is available in local mode or external storage.";
    }

    results.append(fragment);
  });
};

const renderEmptyState = (message) => {
  results.innerHTML = `<div class="empty-state">${message}</div>`;
  resultCount.textContent = "0 passages";
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

const renderRepoDrop = (files) => {
  repoDropList.innerHTML = "";
  if (!files.length) {
    repoDropList.innerHTML = '<div class="empty-state">The repo drop is empty. Developers can commit PDFs into <code>repo-pdf-drop/</code> and import them here.</div>';
    return;
  }

  files.slice(0, 8).forEach((file) => {
    const fragment = listCardTemplate.content.cloneNode(true);
    fragment.querySelector(".item-name").textContent = file.filename;
    fragment.querySelector(".item-summary").textContent =
      `${Math.max(1, Math.round(file.size / 1024 / 1024))} MB | committed developer upload`;
    fragment.querySelector(".item-detail").textContent = "Ready to import while staying in the repo drop folder";
    repoDropList.append(fragment);
  });
};

const renderSourceList = () => {
  sourceList.innerHTML = "";
  library.sources.slice(0, 6).forEach((source) => {
    const fragment = listCardTemplate.content.cloneNode(true);
    fragment.querySelector(".item-name").textContent = source.title;
    fragment.querySelector(".item-summary").textContent =
      `${source.excerptCount} excerpts | ${source.subject ? `${source.topic} / ${source.subject}` : source.topic}`;
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
  renderTopics();
  renderSubjects();
  renderSources();
  renderSourceList();
};

const searchEvidence = async () => {
  const query = queryInput.value.trim();
  if (!query) {
    statusMessage.textContent = "Enter a prompt, question, or statement first. The app will answer only from the committed library.";
    answerStatus.textContent = "Waiting for a question";
    answerCard.textContent = "The response panel will answer only from the committed PDF evidence library.";
    answerCitations.innerHTML = "";
    renderEmptyState("No search has been run yet.");
    return;
  }

  try {
    const response = await fetch("/api/answer", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        query,
        topic: topicFilter.value,
        subject: subjectFilter.value,
        sourceId: sourceFilter.value
      })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Answering failed.");
    }

    renderAnalysis(payload.analysis);
    renderAnswer(payload);
    renderResults(payload.matches || []);
    statusMessage.textContent = payload.analysis.exactPhrases.length
      ? "Response completed with quoted exact constraints against the shared repo library."
      : "Response completed from the shared repo library using evidence analysis.";
    return;
  } catch (error) {
    const analysis = analyzeQuestion(query);
    renderAnalysis(analysis);
    const matches = library.records
      .filter((record) => !topicFilter.value || record.topic === topicFilter.value)
      .filter((record) => !subjectFilter.value || normalizeOptionalText(record.subject) === subjectFilter.value)
      .filter((record) => !sourceFilter.value || record.sourceRef === sourceFilter.value)
      .map((record) => scoreRecord(record, analysis))
      .filter(Boolean)
      .sort((left, right) => right.score - left.score || left.page - right.page)
      .slice(0, 50);

    renderFallbackAnswer(matches);
    statusMessage.textContent = error.message;
    renderResults(matches);
  }
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

const refreshRepoDrop = async () => {
  if (!localMode) return;
  const response = await fetch("/api/repo-drop", { cache: "no-store" });
  const payload = await response.json();
  renderRepoDrop(payload.files || []);
};

const refreshLibraryPdfs = async () => {
  if (!localMode) return;
  const response = await fetch("/api/library-pdfs", { cache: "no-store" });
  const payload = await response.json();
  libraryPdfList.innerHTML = "";
  if (!(payload.files || []).length) {
    libraryPdfList.innerHTML = '<div class="empty-state">All committed library PDFs are already indexed.</div>';
    return;
  }
  (payload.files || []).slice(0, 10).forEach((file) => {
    const fragment = listCardTemplate.content.cloneNode(true);
    fragment.querySelector(".item-name").textContent = file.filename;
    fragment.querySelector(".item-summary").textContent =
      `${Math.max(1, Math.round(file.size / 1024 / 1024))} MB | committed library PDF`;
    fragment.querySelector(".item-detail").textContent = "Ready to index from library-assets/pdfs";
    libraryPdfList.append(fragment);
  });
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
    repoDropForm.classList.remove("hidden");
    libraryPdfForm.classList.remove("hidden");
    blobSyncForm.classList.remove("hidden");
    uploadModeMessage.textContent =
      "Local mode is active. Add a topic, optionally add a subject, then upload directly, import from library-inbox/, index committed library PDFs, or import developer PDFs from repo-pdf-drop/. PDFs without a usable text layer will try OCR during ingestion when an OpenAI key is available.";
  } else {
    uploadForm.classList.add("hidden");
    inboxForm.classList.add("hidden");
    repoDropForm.classList.add("hidden");
    libraryPdfForm.classList.add("hidden");
    blobSyncForm.classList.add("hidden");
    uploadModeMessage.textContent =
      "Shared mode is read-only. Run locally if you need to add books into the repo library or sync PDFs to Vercel Blob.";
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
  await Promise.all([fetchLibrary(), refreshJobs(), refreshInbox(), refreshRepoDrop(), refreshLibraryPdfs()]);
};

const handleInboxImport = async (event) => {
  event.preventDefault();
  uploadStatus.textContent = "Importing PDFs from library-inbox into the shared repo library...";

  const response = await fetch("/api/import-inbox", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      topic: document.querySelector("#upload-topic").value.trim(),
      subject: document.querySelector("#upload-subject").value.trim(),
      author: document.querySelector("#upload-author").value.trim(),
      year: document.querySelector("#upload-year").value.trim()
    })
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Inbox import failed.");
  }

  const skipped = payload.skipped?.length ? ` Skipped duplicates: ${payload.skipped.join(", ")}.` : "";
  uploadStatus.textContent = `${payload.message}${skipped}`;
  renderJobs(payload.jobs || []);
  await Promise.all([fetchLibrary(), refreshJobs(), refreshInbox(), refreshRepoDrop(), refreshLibraryPdfs()]);
};

const handleRepoDropImport = async (event) => {
  event.preventDefault();
  uploadStatus.textContent = "Importing PDFs from repo-pdf-drop into the shared repo library...";

  const response = await fetch("/api/import-repo-drop", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      topic: document.querySelector("#upload-topic").value.trim(),
      subject: document.querySelector("#upload-subject").value.trim(),
      author: document.querySelector("#upload-author").value.trim(),
      year: document.querySelector("#upload-year").value.trim()
    })
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Repo drop import failed.");
  }

  const skipped = payload.skipped?.length ? ` Skipped duplicates: ${payload.skipped.join(", ")}.` : "";
  uploadStatus.textContent = `${payload.message}${skipped}`;
  renderJobs(payload.jobs || []);
  await Promise.all([fetchLibrary(), refreshJobs(), refreshInbox(), refreshRepoDrop(), refreshLibraryPdfs()]);
};

const handleLibraryPdfImport = async (event) => {
  event.preventDefault();
  uploadStatus.textContent = "Indexing committed PDFs from library-assets/pdfs...";

  const response = await fetch("/api/import-library-pdfs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      topic: document.querySelector("#upload-topic").value.trim(),
      subject: document.querySelector("#upload-subject").value.trim(),
      author: document.querySelector("#upload-author").value.trim(),
      year: document.querySelector("#upload-year").value.trim()
    })
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Committed library import failed.");
  }

  const skipped = payload.skipped?.length ? ` Skipped duplicates: ${payload.skipped.join(", ")}.` : "";
  uploadStatus.textContent = `${payload.message}${skipped}`;
  renderJobs(payload.jobs || []);
  await Promise.all([fetchLibrary(), refreshJobs(), refreshInbox(), refreshRepoDrop(), refreshLibraryPdfs()]);
};

const handleBlobSync = async (event) => {
  event.preventDefault();
  uploadStatus.textContent = "Syncing indexed PDFs to Vercel Blob...";

  const response = await fetch("/api/sync-blob", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: "{}"
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Blob sync failed.");
  }

  const skipped = payload.skipped?.length ? ` Skipped: ${payload.skipped.length}.` : "";
  uploadStatus.textContent = `${payload.message}${skipped}`;
  await fetchLibrary();
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

repoDropForm.addEventListener("submit", (event) => {
  handleRepoDropImport(event).catch((error) => {
    uploadStatus.textContent = error.message;
  });
});

libraryPdfForm.addEventListener("submit", (event) => {
  handleLibraryPdfImport(event).catch((error) => {
    uploadStatus.textContent = error.message;
  });
});

blobSyncForm.addEventListener("submit", (event) => {
  handleBlobSync(event).catch((error) => {
    uploadStatus.textContent = error.message;
  });
});

topicFilter.addEventListener("change", () => {
  renderSubjects();
  renderSources();
});

subjectFilter.addEventListener("change", () => {
  renderSources();
});

topicSearch.addEventListener("input", () => {
  renderTopics();
});

subjectSearch.addEventListener("input", () => {
  renderSubjects();
  renderSources();
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
    renderEmptyState("The shared repo library is ready. Ask a question or test a claim against the evidence.");
    renderAnswer({
      grounded: false,
      overallAssessment: "insufficient",
      answer: "The response panel will write only from the committed PDF evidence library.",
      supportingEvidence: [],
      opposingEvidence: [],
      usedCitations: []
    });
    return Promise.all([refreshJobs(), refreshInbox(), refreshRepoDrop(), refreshLibraryPdfs()]);
  })
  .catch((error) => {
    statusMessage.textContent = error.message;
    renderEmptyState("The shared repo library could not be loaded.");
  });
