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
    "say", "says", "said", "saying", "would", "could", "can", "please", "show", "prompt",
    "question", "statement", "claim", "prove", "proof", "against", "for"
}

RELATED_TERMS = {
    "adhan": ["athan", "azan", "call", "prayer"],
    "aqidah": ["belief", "creed"],
    "hadith": ["hadeeth", "hadis", "narration", "report"],
    "imam": ["leader"],
    "intention": ["niyyah", "niyat", "deed", "actions"],
    "islam": ["muslim", "deen", "faith"],
    "prayer": ["salah", "salat", "namaz"],
    "quran": ["qur-an", "koran", "revelation", "verse"],
    "tafsir": ["tafseer", "tefsir", "explanation", "commentary"],
    "wudu": ["wudhu", "ablution"],
}

VARIANT_GROUPS = [
    ["adhan", "athan", "azan"],
    ["aqidah", "aqeedah"],
    ["dua", "duaa", "dua'a", "du'a", "supplication"],
    ["hadith", "hadeeth", "hadis"],
    ["intention", "niyyah", "niyat"],
    ["imam", "imaam"],
    ["prayer", "salah", "salat", "namaz"],
    ["quran", "qur-an", "koran"],
    ["tafsir", "tafseer", "tefsir"],
    ["wudu", "wudhu", "ablution"],
]

SUPPORT_CUES = [
    "commanded", "encouraged", "permitted", "prescribed", "affirmed", "allowed", "recommended",
    "should", "must", "is from", "said", "says", "narrated", "verse", "ayah", "indeed"
]

OPPOSE_CUES = [
    "forbidden", "prohibited", "not", "no", "never", "avoid", "warned", "disliked", "invalid",
    "false", "denied", "refuted"
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


def unique(values):
    return sorted(set(value for value in values if value))


def normalize_term(term: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", term.lower())
    if compact in VARIANT_CANONICAL:
        return VARIANT_CANONICAL[compact]
    if len(compact) > 5 and compact.endswith("ies"):
        return f"{compact[:-3]}y"
    if len(compact) > 4 and compact.endswith("ing"):
        return compact[:-3]
    if len(compact) > 3 and compact.endswith("ed"):
        return compact[:-2]
    if len(compact) > 4 and compact.endswith("es"):
        return compact[:-2]
    if len(compact) > 3 and compact.endswith("s"):
        return compact[:-1]
    return compact


def tokenize(text: str):
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return [token for token in cleaned.split() if token and token not in STOP_WORDS]


def build_concept_phrases(tokens):
    phrases = []
    for size in (4, 3, 2):
        for index in range(0, len(tokens) - size + 1):
            phrase = " ".join(tokens[index:index + size])
            if phrase not in phrases:
                phrases.append(phrase)
    return phrases[:10]


def detect_prompt_mode(prompt: str):
    lowered = prompt.lower()
    if re.search(r"\b(true|false|correct|incorrect|right|wrong)\b", lowered):
        return "evaluate-claim"
    if re.search(r"\b(prove|proof|evidence for|evidence against|support|refute|contradict)\b", lowered):
        return "weigh-evidence"
    if re.search(r"\b(compare|difference|versus|vs\.?)\b", lowered):
        return "compare"
    if re.search(r"\?$", lowered.strip()) or re.search(r"\bwhat|when|where|who|why|how\b", lowered):
        return "question"
    return "statement"


def analyze_prompt(prompt: str):
    lowered = prompt.lower()
    exact_phrases = [match.group(1).strip() for match in re.finditer(r'"([^"]+)"', prompt) if match.group(1).strip()]
    unquoted = re.sub(r'"[^"]+"', " ", prompt)
    raw_tokens = tokenize(unquoted)
    focus_terms = unique(
        normalize_term(token)
        for token in raw_tokens
        if len(normalize_term(token)) > 2
    )[:14]
    concept_phrases = build_concept_phrases(raw_tokens)
    expanded_terms = set(focus_terms)
    for term in focus_terms:
        for related in RELATED_TERMS.get(term, []):
            expanded_terms.add(normalize_term(related))
        for variant in VARIANT_EXPANSIONS.get(term, []):
            expanded_terms.add(variant)

    intent_terms = []
    if re.search(r"\b(say|recite|repeat|words?)\b", lowered):
        intent_terms.extend(["say", "repeat", "recite", "words", "hear", "respond"])
    if re.search(r"\b(where|from)\b", lowered):
        intent_terms.extend(["from", "born", "place", "city", "land"])
    if re.search(r"\b(proof|evidence|support)\b", lowered):
        intent_terms.extend(["proof", "support", "evidence", "confirm"])
    if re.search(r"\b(against|refute|oppose|contradict)\b", lowered):
        intent_terms.extend(["against", "refute", "oppose", "contradict"])

    return {
        "originalPrompt": prompt,
        "promptMode": detect_prompt_mode(prompt),
        "exactPhrases": exact_phrases,
        "focusTerms": focus_terms,
        "conceptPhrases": concept_phrases,
        "expandedTerms": list(expanded_terms)[:40],
        "intentTerms": unique(intent_terms),
        "mode": "quoted-exact" if exact_phrases else "evidence-analysis",
        "supportingConcepts": [],
        "opposingConcepts": [],
        "intent": "",
    }


def call_openai_retrieval_plan(prompt: str, topic="", subject=""):
    load_env_from_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.environ.get("OPENAI_ANSWER_MODEL", "gpt-4.1-mini")
    payload = {
        "model": model,
        "instructions": (
            "Analyze the user's prompt for evidence retrieval. "
            "Return strict JSON with keys focusTerms, supportingConcepts, opposingConcepts, variantTerms, intent, and promptMode. "
            "Do not answer the prompt."
        ),
        "input": (
            f"Prompt: {prompt}\n"
            f"Topic filter: {topic or 'Any'}\n"
            f"Subject filter: {subject or 'Any'}\n"
            "Return JSON only."
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
        parsed = json.loads(body.get("output_text", "").strip())
    except Exception:
        return None

    return {
        "focusTerms": [normalize_term(item) for item in parsed.get("focusTerms", []) if isinstance(item, str)],
        "supportingConcepts": [item.strip() for item in parsed.get("supportingConcepts", []) if isinstance(item, str) and item.strip()],
        "opposingConcepts": [item.strip() for item in parsed.get("opposingConcepts", []) if isinstance(item, str) and item.strip()],
        "variantTerms": [normalize_term(item) for item in parsed.get("variantTerms", []) if isinstance(item, str)],
        "intent": (parsed.get("intent") or "").strip(),
        "promptMode": (parsed.get("promptMode") or "").strip(),
    }


def merge_analysis(prompt: str, topic="", subject=""):
    analysis = analyze_prompt(prompt)
    plan = call_openai_retrieval_plan(prompt, topic=topic, subject=subject)
    if not plan:
        return analysis

    merged_focus = unique(list(analysis["focusTerms"]) + plan["focusTerms"] + plan["variantTerms"])[:16]
    expanded = set(analysis["expandedTerms"])
    for term in merged_focus + plan["variantTerms"]:
        expanded.add(term)
        for variant in VARIANT_EXPANSIONS.get(term, []):
            expanded.add(variant)

    concepts = analysis["conceptPhrases"][:]
    for phrase in plan["supportingConcepts"] + plan["opposingConcepts"]:
        if phrase not in concepts:
            concepts.append(phrase)

    analysis.update({
        "focusTerms": merged_focus,
        "expandedTerms": list(expanded)[:48],
        "conceptPhrases": concepts[:14],
        "supportingConcepts": plan["supportingConcepts"],
        "opposingConcepts": plan["opposingConcepts"],
        "intent": plan["intent"],
        "promptMode": plan["promptMode"] or analysis["promptMode"],
    })
    return analysis


def token_positions(tokens):
    positions = {}
    for index, token in enumerate(tokens):
        normalized = normalize_term(token)
        positions.setdefault(normalized, []).append(index)
    return positions


def concept_present(phrase, positions_map, window=16):
    terms = [normalize_term(term) for term in tokenize(phrase)]
    if not terms or any(term not in positions_map for term in terms):
        return False

    for anchor in positions_map[terms[0]]:
        if all(any(abs(position - anchor) <= window for position in positions_map[term]) for term in terms[1:]):
            return True
    return False


def direction_from_text(text, analysis):
    lowered = text.lower()
    support_hits = [phrase for phrase in analysis.get("supportingConcepts", []) if phrase.lower() in lowered]
    oppose_hits = [phrase for phrase in analysis.get("opposingConcepts", []) if phrase.lower() in lowered]
    support_score = len(support_hits) * 18
    oppose_score = len(oppose_hits) * 18

    support_score += sum(3 for cue in SUPPORT_CUES if cue in lowered)
    oppose_score += sum(3 for cue in OPPOSE_CUES if cue in lowered)

    negation_present = any(cue in lowered for cue in (" not ", " no ", " never ", " forbidden ", " prohibited "))
    if analysis["promptMode"] in {"question", "statement"} and not analysis.get("opposingConcepts"):
        if negation_present:
            oppose_score += 4
        else:
            support_score += 2

    if support_score > oppose_score + 4:
        return "support", support_hits, oppose_hits
    if oppose_score > support_score + 4:
        return "oppose", support_hits, oppose_hits
    return "related", support_hits, oppose_hits


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
    normalized_set = {normalize_term(token) for token in raw_tokens}
    positions_map = token_positions(raw_tokens)

    exact_phrase_hits = [
        phrase for phrase in analysis["exactPhrases"]
        if phrase.lower() in record.get("excerpt", "").lower() or phrase.lower() in record.get("title", "").lower()
    ]
    if analysis["exactPhrases"] and len(exact_phrase_hits) != len(analysis["exactPhrases"]):
        return None

    focus_hits = [term for term in analysis["focusTerms"] if term in normalized_set]
    expanded_hits = [term for term in analysis["expandedTerms"] if term in normalized_set and term not in focus_hits]
    intent_hits = [term for term in analysis.get("intentTerms", []) if normalize_term(term) in normalized_set]
    concept_hits = [phrase for phrase in analysis["conceptPhrases"] if concept_present(phrase, positions_map)]
    title_text = " ".join([
        record.get("title", ""),
        record.get("author", ""),
        record.get("topic", ""),
        record.get("subject", ""),
    ]).lower()
    title_focus_hits = [term for term in analysis["focusTerms"] if term in title_text]

    if analysis["focusTerms"] and not (focus_hits or exact_phrase_hits or title_focus_hits or concept_hits):
        return None

    direction, support_hits, oppose_hits = direction_from_text(record.get("excerpt", ""), analysis)

    score = 0
    score += len(exact_phrase_hits) * 120
    score += len(concept_hits) * 24
    score += len(focus_hits) * 14
    score += min(len(expanded_hits), 8) * 5
    score += len(intent_hits) * 8
    score += len(title_focus_hits) * 12
    score += len(support_hits) * 16
    score += len(oppose_hits) * 16
    if direction == "support":
        score += 10
    elif direction == "oppose":
        score += 10
    else:
        score += 4

    if score <= 0:
        return None

    matches = unique(
        [f'"{phrase}"' for phrase in exact_phrase_hits]
        + concept_hits[:4]
        + focus_hits[:8]
        + expanded_hits[:6]
    )

    enriched = dict(record)
    enriched.update({
        "score": score,
        "exactPhraseMatch": bool(exact_phrase_hits),
        "conceptHits": concept_hits,
        "focusHits": focus_hits,
        "intentHits": intent_hits,
        "supportHits": support_hits,
        "opposingHits": oppose_hits,
        "evidenceDirection": direction,
        "matches": matches,
    })
    return enriched


def search_library(library, prompt, topic="", subject="", source_id=""):
    analysis = merge_analysis(prompt, topic=topic, subject=subject)
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
    return analysis, matches[:24]


def build_citations(matches):
    citations = []
    for index, match in enumerate(matches[:10], start=1):
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
            "supportHits": match.get("supportHits", []),
            "opposingHits": match.get("opposingHits", []),
            "evidenceDirection": match.get("evidenceDirection", "related"),
            "matches": match.get("matches", []),
            "score": match.get("score", 0),
        })
    return citations


def split_citations(citations):
    supporting = [item for item in citations if item.get("evidenceDirection") == "support"]
    opposing = [item for item in citations if item.get("evidenceDirection") == "oppose"]
    related = [item for item in citations if item.get("evidenceDirection") == "related"]
    return supporting, opposing, related


def fallback_answer(prompt, citations, analysis):
    supporting, opposing, related = split_citations(citations)
    if not citations:
        return {
            "answer": "The current library does not contain enough relevant evidence to answer that yet.",
            "summary": "No strong supporting or opposing evidence was retrieved from the available files.",
            "grounded": False,
            "usedCitations": [],
            "supportMarkers": [],
            "againstMarkers": [],
            "overallAssessment": "insufficient",
        }

    if supporting and not opposing:
        lead = supporting[0]
        answer = (
            f"The strongest evidence in the current library supports the prompt, mainly from {lead['title']} on page "
            f"{lead['page']} [{lead['marker']}]."
        )
        assessment = "mostly-supported"
    elif opposing and not supporting:
        lead = opposing[0]
        answer = (
            f"The strongest evidence in the current library challenges the prompt, mainly from {lead['title']} on page "
            f"{lead['page']} [{lead['marker']}]."
        )
        assessment = "mostly-opposed"
    else:
        lead = citations[0]
        answer = (
            f"The current library contains mixed or partial evidence, with the most relevant passage coming from "
            f"{lead['title']} on page {lead['page']} [{lead['marker']}]."
        )
        assessment = "mixed"

    return {
        "answer": answer,
        "summary": answer,
        "grounded": True,
        "usedCitations": [item["marker"] for item in citations[:4]],
        "supportMarkers": [item["marker"] for item in supporting[:4]],
        "againstMarkers": [item["marker"] for item in opposing[:4]],
        "overallAssessment": assessment,
    }


def call_openai_answer(prompt, citations, analysis):
    load_env_from_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not citations:
        return fallback_answer(prompt, citations, analysis)

    model = os.environ.get("OPENAI_ANSWER_MODEL", "gpt-4.1-mini")
    evidence_lines = []
    for citation in citations:
        evidence_lines.append(
            f"[{citation['marker']}] Direction: {citation['evidenceDirection']} | {citation['title']} | "
            f"{citation['author']} | {citation['year']} | Topic: {citation.get('topic') or 'None'} | "
            f"Subject: {citation.get('subject') or 'None'} | Page {citation['page']} | Excerpt: {citation['excerpt']}"
        )

    payload = {
        "model": model,
        "instructions": (
            "Use only the supplied evidence. "
            "Decide which snippets support the prompt, which challenge it, and which are merely related. "
            "Write a concise answer in your own wording based only on that evidence. "
            "Do not invent facts. If evidence is incomplete or mixed, say so plainly. "
            "Return strict JSON with keys answer, summary, usedCitations, supportMarkers, againstMarkers, and overallAssessment. "
            "overallAssessment must be one of: mostly-supported, mostly-opposed, mixed, insufficient."
        ),
        "input": (
            f"Prompt: {prompt}\n"
            f"Prompt mode: {analysis.get('promptMode')}\n"
            f"Focus terms: {', '.join(analysis.get('focusTerms', []))}\n\n"
            "Evidence:\n" + "\n".join(evidence_lines)
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
        with request.urlopen(req, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(body.get("output_text", "").strip())
    except Exception:
        return fallback_answer(prompt, citations, analysis)

    valid_markers = {citation["marker"] for citation in citations}
    used_markers = [marker for marker in parsed.get("usedCitations", []) if isinstance(marker, int) and marker in valid_markers]
    support_markers = [marker for marker in parsed.get("supportMarkers", []) if isinstance(marker, int) and marker in valid_markers]
    against_markers = [marker for marker in parsed.get("againstMarkers", []) if isinstance(marker, int) and marker in valid_markers]
    assessment = parsed.get("overallAssessment", "").strip()
    if assessment not in {"mostly-supported", "mostly-opposed", "mixed", "insufficient"}:
        assessment = fallback_answer(prompt, citations, analysis)["overallAssessment"]

    return {
        "answer": parsed.get("answer", "").strip() or fallback_answer(prompt, citations, analysis)["answer"],
        "summary": parsed.get("summary", "").strip() or parsed.get("answer", "").strip(),
        "grounded": True,
        "usedCitations": used_markers or [citation["marker"] for citation in citations[:4]],
        "supportMarkers": support_markers,
        "againstMarkers": against_markers,
        "overallAssessment": assessment,
    }


def answer_question(prompt, topic="", subject="", source_id=""):
    library = load_library()
    analysis, matches = search_library(library, prompt, topic=topic, subject=subject, source_id=source_id)
    citations = build_citations(matches)
    answer = call_openai_answer(prompt, citations, analysis)

    marker_set = set(answer.get("usedCitations", []))
    support_set = set(answer.get("supportMarkers", []))
    against_set = set(answer.get("againstMarkers", []))

    return {
        "analysis": analysis,
        "answer": answer["answer"],
        "summary": answer.get("summary", ""),
        "grounded": answer["grounded"],
        "overallAssessment": answer.get("overallAssessment", "insufficient"),
        "usedCitations": [citation for citation in citations if citation["marker"] in marker_set] or citations[:4],
        "supportingEvidence": [citation for citation in citations if citation["marker"] in support_set],
        "opposingEvidence": [citation for citation in citations if citation["marker"] in against_set],
        "relatedEvidence": [
            citation for citation in citations
            if citation["marker"] not in support_set and citation["marker"] not in against_set
        ],
        "matches": matches,
    }
