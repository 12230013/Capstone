import json
import re
import sys

try:
    import config
except (ImportError, ModuleNotFoundError):
    from acc_statements import config

FIELD_LABELS = {
    "name": ["name"],
    "gender": ["gender", "sex"],
    "cid": ["cid no.", "cid no", "cid number", "cid"],
    "dob": ["date of birth", "dob"],
    "village": ["village"],
    "gewog": ["gewog"],
    "dzongkhag": ["dzongkhag", "dzongkhang"],
    "phone_number": ["phone number", "phone no.", "phone no", "phone"],
    "occupation": ["occupation"],
    "email": ["email id", "email"],
    "address": ["address"],
    "employment": ["employment details", "employment detail", "employment"],
    "written_read_by": ["written/read by", "written / read by", "written by", "read by"],
    "statement_date": ["date"],
    "administered_by": ["administered by"],
    "case_no": ["case no.", "case no", "case number"],
    "start_time": ["start time"],
    "end_time": ["end time"],
    "place": ["place"],
    "statement": ["statement"],
}

LABEL_TO_KEY = {lab: key for key, labs in FIELD_LABELS.items() for lab in labs}
_labels_sorted = sorted(LABEL_TO_KEY, key=len, reverse=True)      # longest first
LABEL_RE = re.compile(
    r"^[ \t]*(?P<label>" + "|".join(re.escape(l) for l in _labels_sorted) + r")[ \t]*:[ \t]*",
    re.IGNORECASE | re.MULTILINE,
)

ABBREVIATIONS = ["Mr.", "Mrs.", "Ms.", "Dr.", "Nu.", "No.", "Lt.", "Col.", "St."]


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    for ab in ABBREVIATIONS:
        text = text.replace(ab, ab.replace(".", "<DOT>"))
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"\'(])', text)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


def parse_statement(path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    doc_id = re.sub(r"[^A-Za-z0-9_]", "_", path.stem)
    matches = list(LABEL_RE.finditer(raw))
    fields = {}
    body = ""
    for i, m in enumerate(matches):
        key = LABEL_TO_KEY[m.group("label").lower()]
        if key in fields or key == "statement" and body:
            continue
        if key == "statement":
            body = raw[m.end():]              # everything after "Statement:" is the narrative
            break
        if i + 1 < len(matches):
            end = matches[i + 1].start()
            fields[key] = re.sub(r"\s+", " ", raw[m.end():end]).strip()
        else:
            line_break = raw.find("\n", m.end())
            if line_break != -1:
                fields[key] = re.sub(r"\s+", " ", raw[m.end():line_break]).strip()
                if not body:
                    body = raw[line_break:].strip()
            else:
                fields[key] = re.sub(r"\s+", " ", raw[m.end():]).strip()

    if not body and matches:
        body = raw[matches[-1].end():].strip()

    # Fill default case_no if absent
    if not fields.get("case_no"):
        fields["case_no"] = "ACC/2024/017"

    # Split body into sentences with IDs
    raw_sentences = split_sentences(body) if body else []
    sentences = [{"id": f"{doc_id}-s{n}", "text": s}
                 for n, s in enumerate(raw_sentences, start=1)]
    doc = {"doc_id": doc_id, "source_file": path.name, "header": fields, "sentences": sentences}

    if not sentences:
        print(f"  WARNING {path.name}: no statement sentences parsed")
    return doc


def load_docs() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(config.PARSED_DIR.glob("*.json"))]


def run_ingest():
    config.PARSED_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(config.DATA_DIR.glob("*.txt"))
    if not files:
        sys.exit(f"No .txt files in {config.DATA_DIR}")
    for p in files:
        doc = parse_statement(p)
        (config.PARSED_DIR / f"{doc['doc_id']}.json").write_text(
            json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        h = doc["header"]
        print(f"  parsed {p.name}: {h.get('name', '?')} | case {h.get('case_no', '?')} | "
              f"{len(doc['sentences'])} sentences")