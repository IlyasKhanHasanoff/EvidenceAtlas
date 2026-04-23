import csv
import json
import re
from datetime import datetime, UTC
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "docs" / "library" / "index.json"
MANIFEST_PATH = ROOT / "docs" / "library" / "source-manifest.json"
DATASET_DIR = ROOT / ".tmp-hadith-datasets" / "All Hadith Books"
SOURCE_ID = "SRC-HADITH-BUKHARI-DATASET"
BOOK_TITLE = "Sahih Bukhari Dataset"
BOOK_AUTHOR = "Imam al-Bukhari"
DATASET_FILE = DATASET_DIR / "Sahih Bukhari Without_Tashkel.csv"
OLD_FILENAMES = {
    "Sahih al-Bukhari Vol. 1 - 1-875 English Arabic.pdf",
}

ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_arabic(text: str) -> str:
    text = ARABIC_DIACRITICS_RE.sub("", text or "")
    text = text.replace("ـ", "")
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ؤ": "و",
        "ئ": "ي",
        "ى": "ي",
        "ة": "ه",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def tokenize(text: str):
    cleaned = re.sub(r"[\W_]+", " ", normalize_arabic((text or "").lower()), flags=re.UNICODE)
    return [token for token in cleaned.split() if token]


def derive_keywords(text: str):
    ordered = []
    seen = set()
    for token in tokenize(text):
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
        if len(ordered) == 16:
            break
    return ordered


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_hadith_rows():
    with DATASET_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = [row for row in reader if row]
    if rows and len(rows[0]) == 1 and "bukhari" in rows[0][0].lower():
        rows = rows[1:]
    hadiths = []
    for row in rows:
        text = normalize_whitespace(" ".join(cell for cell in row if cell))
        if not text:
            continue
        hadiths.append(text)
    return hadiths


def build_records(hadiths):
    records = []
    for index, text in enumerate(hadiths, start=1):
        records.append(
            {
                "sourceId": f"{SOURCE_ID}-H{index:05d}",
                "sourceRef": SOURCE_ID,
                "title": BOOK_TITLE,
                "author": BOOK_AUTHOR,
                "year": "2022",
                "topic": "Islam",
                "subject": "Hadith",
                "page": index,
                "locatorLabel": f"Hadith {index}",
                "sourceType": "hadith-dataset",
                "excerpt": text,
                "searchText": normalize_arabic(text),
                "keywords": derive_keywords(text),
                "pdfPath": "",
                "originalFilename": DATASET_FILE.name,
            }
        )
    return records


def main():
    library = load_json(INDEX_PATH)
    manifest = load_json(MANIFEST_PATH)
    hadiths = read_hadith_rows()
    records = build_records(hadiths)

    filtered_sources = []
    for source in library.get("sources", []):
        original_name = source.get("originalFilename")
        if source.get("subject") == "Hadith":
            continue
        if original_name in OLD_FILENAMES:
            continue
        filtered_sources.append(source)

    filtered_records = [
        record
        for record in library.get("records", [])
        if record.get("subject") != "Hadith" and record.get("originalFilename") not in OLD_FILENAMES
    ]

    filtered_sources.insert(
        0,
        {
            "sourceId": SOURCE_ID,
            "title": BOOK_TITLE,
            "author": BOOK_AUTHOR,
            "year": "2022",
            "topic": "Islam",
            "subject": "Hadith",
            "pdfPath": "",
            "originalFilename": DATASET_FILE.name,
            "sourceType": "hadith-dataset",
            "ingestionStatus": "indexed",
            "excerptCount": len(records),
        },
    )

    library["generatedAt"] = datetime.now(UTC).isoformat()
    library["sources"] = filtered_sources
    library["records"] = records + filtered_records

    manifest.pop("Sahih al-Bukhari Vol. 1 - 1-875 English Arabic.pdf", None)
    manifest[DATASET_FILE.name] = {
        "topic": "Islam",
        "subject": "Hadith",
        "title": BOOK_TITLE,
        "author": BOOK_AUTHOR,
        "year": "2022",
        "sourceType": "hadith-dataset",
    }

    INDEX_PATH.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Replaced hadith PDF source with {len(records)} dataset-backed hadith records.")


if __name__ == "__main__":
    main()
