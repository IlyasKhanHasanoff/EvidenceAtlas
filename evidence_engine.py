import json
import os
import re
from pathlib import Path
from urllib import request


ROOT = Path(__file__).parent
INDEX_PATH = ROOT / "docs" / "library" / "index.json"
ENV_PATH = ROOT / ".env"

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "into", "is",
    "it", "of", "on", "or", "that", "the", "there", "this", "to", "was", "what", "when", "where",
    "which", "who", "why", "with", "evidence", "find", "about", "tell", "me", "i", "should",
    "say", "says", "said", "saying", "would", "could", "can"
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

VARIANT_GROUPS = [
    ["adhan", "athan", "azan", "adhan"],
    ["hadith", "hadeeth", "hadis"],
    ["tafsir", "tafseer", "tefsir"],
    ["quran", "qur-an", "koran"],
    ["salah", "salat", "namaz"],
    ["dua", "duaa", "du'a", "supplication"],
]

VARIANT_CANONICAL = {}
VARIANT_EXPANSIONS = {}
for group in VARIANT_GROUPS:
    canonical = group[0]
    normalized_group = set()
    for item in group:
        normalized = re.sub(r"[^a-z0-9]", "", item.lower())
        normalized_group.add(normalized)
        VARIANT_CANONICAL[normalized] = canonical
    for item in normalized_group:
        VARIANT_EXPANSIONS[item] = sorted(normalized_group)


def load_env_from_file():
    if os.environ.get("OPENAI_API_KEY") or not ENV_PATH.exists():
        return

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_library():
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def normalize_term(term: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", term.lower())
    if compact in VARIANT_CANONICAL:
        return VARIANT_CANONICAL[compact]

    if len(term) > 5 and term.endswith("ies"):
        return f"{term[:-3]}y"
    if len(term) > 4 and term.endswith("ing"):
        return term[:-3]
    if len(term) > 3 and term.endswith("ed"):
        return term[:-2]
    if len(term) > 4 and term.endswith("es"):
        return term[:-2]
    if len(term) > 3 and term.endswith("s"):
        return term[:-1]
    return term


def unique(values):
    return sorted(set(values))


def tokenize(text: str):
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return [token for token in cleaned.split() if token and token not in STOP_WORDS]


def build_concept_phrases(tokens):
    phrases = []
    for size in (3, 2):
        for index in range(0, len(tokens) - size + 1):
            phrase = " ".join(tokens[index:index + size])
            if phrase not in phrases:
                phrases.append(phrase)
    return phrases[:6]


def analyze_question(query: str):
    lowered = query.lower()
    exact_phrases = [match.group(1).strip() for match in re.finditer(r'"([^"]+)"', query) if match.group(1).strip()]
    unquoted = re.sub(r'"[^"]+"', " ", query)
    raw_tokens = tokenize(unquoted)
    focus_terms = unique(
        normalize_term(token)
        for token in raw_tokens
        if len(normalize_term(token)) > 2
    )[:10]
    concept_phrases = build_concept_phrases(raw_tokens)
    expanded_terms = set(focus_terms)

    for term in focus_terms:
        for related in RELATED_TERMS.get(term, []):
            expanded_terms.add(related)
        for variant in VARIANT_EXPANSIONS.get(term, []):
            expanded_terms.add(variant)

    intent_terms = []
    if re.search(r"\b(say|recite|repeat|words?)\b", lowered):
        intent_terms.extend(["say", "repeat", "recite", "words", "hear"])
    if re.search(r"\b(where|from)\b", lowered):
        intent_terms.extend(["from", "born", "place", "city"])

    return {
        "originalQuery": query,
        "exactPhrases": exact_phrases,
        "focusTerms": focus_terms,
        "conceptPhrases": concept_phrases,
        "expandedTerms": list(expanded_terms)[:24],
        "intentTerms": unique(intent_terms),
        "mode": "quoted-exact" if exact_phrases else "analyzed",
    }


def token_positions(tokens):
    positions = {}
    for index, token in enumerate(tokens):
        normalized = normalize_term(token)
        positions.setdefault(normalized, []).append(index)
    return positions


def concept_present(phrase, positions_map, window=10):
    terms = [normalize_term(term) for term in tokenize(phrase)]
    if not terms or any(term not in positions_map for term in terms):
        return False

    for anchor in positions_map[terms[0]]:
        if all(any(abs(position - anchor) <= window for position in positions_map[term]) for term in terms[1:]):
            return True
    return False


def score_record(record, analysis):
    full_text = " ".join([
        record.get("title", ""),
        record.get("author", ""),
        record.get("topic", ""),
        record.get("subject", ""),
        record.get("excerpt", ""),
        " ".join(record.get("keywords", [])),
    ])
    raw_tokens = re.findall(r"[a-z0-9]+", full_text.lower())
    normalized_tokens = [normalize_term(token) for token in raw_tokens]
    normalized_set = set(normalized_tokens)
    positions_map = token_positions(raw_tokens)

    exact_phrase_hits = [
        phrase for phrase in analysis["exactPhrases"]
        if phrase.lower() in record.get("excerpt", "").lower() or phrase.lower() in record.get("title", "").lower()
    ]

    if analysis["exactPhrases"] and len(exact_phrase_hits) != len(analysis["exactPhrases"]):
        return None

    focus_hits = [term for term in analysis["focusTerms"] if term in normalized_set]
    expanded_hits = [term for term in analysis["expandedTerms"] if term in normalized_set and term not in focus_hits]
    intent_hits = [term for term in analysis.get("intentTerms", []) if term in normalized_set]
    concept_hits = [phrase for phrase in analysis["conceptPhrases"] if concept_present(phrase, positions_map)]
    title_text = " ".join([
        record.get("title", ""),
        record.get("author", ""),
        record.get("topic", ""),
        record.get("subject", ""),
    ]).lower()
    title_focus_hits = [term for term in analysis["focusTerms"] if term in title_text]

    if analysis["focusTerms"] and not (focus_hits or exact_phrase_hits or title_focus_hits):
        return None

    score = 0
    score += len(exact_phrase_hits) * 120
    score += len(concept_hits) * 22
    score += len(focus_hits) * 8
    score += min(len(expanded_hits), 6) * 3
    score += len(intent_hits) * 10
    score += len(title_focus_hits) * 10

    if score <= 0:
        return None

    matches = unique(
        [f'"{phrase}"' for phrase in exact_phrase_hits]
        + concept_hits[:4]
        + focus_hits[:6]
        + expanded_hits[:4]
    )

    enriched = dict(record)
    enriched.update({
        "score": score,
        "exactPhraseMatch": bool(exact_phrase_hits),
        "conceptHits": concept_hits,
        "focusHits": focus_hits,
        "intentHits": intent_hits,
        "matches": matches,
    })
    return enriched


def search_library(library, query, topic="", subject="", source_id=""):
    analysis = analyze_question(query)
    matches = []

    for record in library.get("records", []):
        if topic and record.get("topic") != topic:
            continue
        if subject and record.get("subject") != subject:
            continue
        if source_id and record.get("sourceRef") != source_id:
            continue

        scored = score_record(record, analysis)
        if scored:
            matches.append(scored)

    matches.sort(key=lambda item: (-item["score"], item.get("page", 0)))
    return analysis, matches[:12]


def build_citations(matches):
    citations = []
    for index, match in enumerate(matches[:5], start=1):
        citations.append({
            "marker": index,
            "sourceId": match.get("sourceRef"),
            "title": match.get("title"),
            "author": match.get("author"),
            "year": match.get("year"),
            "topic": match.get("topic"),
            "subject": match.get("subject"),
            "page": match.get("page"),
            "excerpt": match.get("excerpt"),
            "pdfPath": match.get("pdfPath"),
        })
    return citations


def fallback_answer(question, citations):
    if not citations:
        return {
        "answer": "The available library does not contain enough cited evidence to answer that question yet.",
        "grounded": False,
        "usedCitations": [],
    }

    lead = citations[0]
    answer = (
        "The closest cited evidence in the current library is "
        f"from {lead['title']} on page {lead['page']}: \"{lead['excerpt']}\" [1]"
    )
    return {
        "answer": answer,
        "grounded": True,
        "usedCitations": [1],
    }


def call_openai_answer(question, citations):
    load_env_from_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not citations:
        return fallback_answer(question, citations)

    model = os.environ.get("OPENAI_ANSWER_MODEL", "gpt-4.1-mini")
    evidence_lines = []
    for citation in citations:
        evidence_lines.append(
            f"[{citation['marker']}] {citation['title']} | {citation['author']} | {citation['year']} | "
            f"Topic: {citation.get('topic') or 'None'} | Subject: {citation.get('subject') or 'None'} | "
            f"Page {citation['page']} | Excerpt: {citation['excerpt']}"
        )

    instructions = (
        "Answer only from the supplied evidence snippets. "
        "If the evidence does not directly support an answer, say so clearly. "
        "Do not use outside knowledge. "
        "Cite claims inline with markers like [1] and [2]. "
        "Return strict JSON with keys answer and usedCitations."
    )

    payload = {
        "model": model,
        "instructions": instructions,
        "input": (
            f"Question: {question}\n\n"
            f"Evidence:\n" + "\n".join(evidence_lines) + "\n\n"
            "Return JSON only. Example: "
            '{"answer":"Frederick Douglass describes ... [1]","usedCitations":[1]}'
        ),
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
        with request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return fallback_answer(question, citations)

    text = body.get("output_text", "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return fallback_answer(question, citations)

    used = [
        marker for marker in parsed.get("usedCitations", [])
        if isinstance(marker, int) and any(citation["marker"] == marker for citation in citations)
    ]

    return {
        "answer": parsed.get("answer", "").strip() or fallback_answer(question, citations)["answer"],
        "grounded": True,
        "usedCitations": used,
    }


def answer_question(question, topic="", subject="", source_id=""):
    library = load_library()
    analysis, matches = search_library(library, question, topic=topic, subject=subject, source_id=source_id)
    citations = build_citations(matches)
    answer = call_openai_answer(question, citations)

    return {
        "analysis": analysis,
        "answer": answer["answer"],
        "grounded": answer["grounded"],
        "usedCitations": [
            citation for citation in citations
            if citation["marker"] in answer.get("usedCitations", [])
        ] or citations[:3],
        "matches": matches,
    }
