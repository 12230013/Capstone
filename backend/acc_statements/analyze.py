import re
from datetime import datetime

import dateparser

try:
    import config
    from llm import ask_json
    from schemas import EntityList, StatementSummary, TimelineExtraction
except (ImportError, ModuleNotFoundError):
    from acc_statements import config
    from acc_statements.llm import ask_json
    from acc_statements.schemas import EntityList, StatementSummary, TimelineExtraction


# ---------- shared helpers ----------
def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def numbered(doc: dict) -> str:
    return "\n".join(f"[{s['id']}] {s['text']}" for s in doc["sentences"])


def header_context(doc: dict) -> str:
    h = doc["header"]
    return (f"Statement given by {h.get('name', 'unknown')} (CID {h.get('cid', 'n/a')}) on "
            f"{h.get('statement_date', 'unknown date')} at {h.get('place', 'unknown place')}, "
            f"Case No. {h.get('case_no', 'n/a')}.")


def locate_quote(doc: dict, quote: str, hint_id: str = ""):
    """Return the sentence ID that really contains the quote, or None. Fixes wrong IDs automatically."""
    q = _norm(quote)
    if not q:
        return None
    by_id = {s["id"]: s["text"] for s in doc["sentences"]}
    if hint_id in by_id and q in _norm(by_id[hint_id]):
        return hint_id
    for s in doc["sentences"]:
        if q in _norm(s["text"]):
            return s["id"]
    return None


def statement_base_date(doc: dict) -> datetime:
    d = dateparser.parse(doc["header"].get("statement_date", ""), settings={"DATE_ORDER": "DMY"})
    return d or datetime.now()


def _warn_if_long(doc):
    total = sum(len(s["text"]) for s in doc["sentences"])
    if total > config.SUMMARY_WARN_CHARS:
        print(f"  WARNING {doc['doc_id']}: {total} chars may exceed the context window. "
              f"Raise LLM_NUM_CTX or add map-reduce summarisation.")


# ---------- 1. summary ----------
SUMMARY_SYSTEM = """You summarise official investigation statements for investigators.
Rules:
- Use ONLY information in the statement. Never add facts, assumptions or legal conclusions.
- Keep names, dates, amounts and places exactly as written.
- Write in neutral third person ("The deponent states ...").
- Each key point must cite the sentence IDs (like stmt_01-s3) it is based on.
- If something is unclear or missing, say so. Do not guess."""


def summarize(doc: dict) -> dict:
    _warn_if_long(doc)
    user = (f"{header_context(doc)}\n\nSTATEMENT (numbered sentences):\n{numbered(doc)}\n\n"
            f"Write a summary of at most {config.SUMMARY_SENTENCES} sentences and 5-8 key points.")
    out = ask_json(SUMMARY_SYSTEM, user, StatementSummary)
    valid_ids = {s["id"] for s in doc["sentences"]}
    key_points = [{"point": k.point, "sentence_ids": [i for i in k.sentence_ids if i in valid_ids],
                   "citations_valid": all(i in valid_ids for i in k.sentence_ids) and bool(k.sentence_ids)}
                  for k in out.key_points]
    return {"doc_id": doc["doc_id"], "person": doc["header"].get("name", ""),
            "summary": out.summary, "key_points": key_points}


# ---------- 2. entities ----------
ENTITY_SYSTEM = """You extract named entities from an investigation statement.
Rules:
- Extract only entities that appear in the numbered sentences. Never invent.
- 'value' must be written exactly as in the text (keep currency, e.g. 'Nu. 50,000').
- 'evidence_quote' must be copied EXACTLY from the cited sentence (a short span is fine).
- 'role_or_context' = what the entity is in this statement (e.g. 'alleged payer', 'meeting venue').
- Types: PERSON, ORGANIZATION, LOCATION, DATE, TIME, MONEY, PHONE_NUMBER, VEHICLE, DOCUMENT, EVENT, OTHER.
- Do NOT list the person giving the statement's own header details; those are captured separately."""


def header_entities(doc: dict) -> list[dict]:
    h = doc["header"]
    rows = [("PERSON", h.get("name"), "person giving statement"),
            ("PERSON", h.get("written_read_by") if h.get("written_read_by", "").lower() != "self" else None,
             "wrote/read statement"),
            ("PERSON", h.get("administered_by"), "administered statement"),
            ("DATE", h.get("statement_date"), "date statement was recorded"),
            ("LOCATION", h.get("place"), "place statement was recorded"),
            ("LOCATION", ", ".join(x for x in [h.get("village"), h.get("gewog"), h.get("dzongkhag")] if x),
             "residence of deponent"),
            ("OTHER", h.get("cid"), "CID of deponent"),
            ("OTHER", h.get("case_no"), "case number")]
    return [{"type": t, "value": v, "role_or_context": c, "source": "header", "verified": True}
            for t, v, c in rows if v]


def extract_entities(doc: dict) -> dict:
    user = f"{header_context(doc)}\n\nSTATEMENT (numbered sentences):\n{numbered(doc)}"
    out = ask_json(ENTITY_SYSTEM, user, EntityList)
    results, seen = header_entities(doc), set()
    for e in out.entities:
        key = (e.type, e.value.lower().strip())
        if key in seen:
            continue
        seen.add(key)
        sid = locate_quote(doc, e.evidence_quote, e.sentence_id)
        results.append({"type": e.type, "value": e.value, "role_or_context": e.role_or_context,
                        "sentence_id": sid or e.sentence_id, "evidence_quote": e.evidence_quote,
                        "source": "llm", "verified": sid is not None})
    return {"doc_id": doc["doc_id"], "person": doc["header"].get("name", ""), "entities": results}


# ---------- 3. timeline ----------
TIMELINE_SYSTEM = """You extract events with time references from an investigation statement.
Rules:
- One entry per distinct event that has, or implies, a date or time.
- 'date_text' and 'time_text' must be the words EXACTLY as written in the statement
  (e.g. '12 March 2024', 'last Tuesday', 'around 2 pm'). Leave '' if the statement gives none.
  Do NOT convert or calculate dates yourself.
- 'event' = short neutral description of what happened. No conclusions.
- 'evidence_quote' must be copied EXACTLY from the cited sentence.
- Include only events described in the statement. Never invent."""


def extract_timeline(doc: dict) -> list[dict]:
    user = f"{header_context(doc)}\n\nSTATEMENT (numbered sentences):\n{numbered(doc)}"
    out = ask_json(TIMELINE_SYSTEM, user, TimelineExtraction)
    base = statement_base_date(doc)
    events = []
    for ev in out.events:
        settings = {"RELATIVE_BASE": base, "PREFER_DATES_FROM": "past", "DATE_ORDER": "DMY"}
        d = dateparser.parse(ev.date_text, settings=settings) if ev.date_text else None
        t = dateparser.parse(ev.time_text, settings=settings) if ev.time_text else None
        sid = locate_quote(doc, ev.evidence_quote, ev.sentence_id)
        if not ev.date_text:
            precision = "no_date_given"
        elif d is None:
            precision = "unparsed"
        elif re.search(r"\d{4}", ev.date_text):
            precision = "explicit_date"
        else:
            precision = "resolved_using_statement_date"      # e.g. 'last Tuesday', '12 March'
        events.append({
            "date": d.date().isoformat() if d else None,
            "time": t.strftime("%H:%M") if t else None,
            "date_text": ev.date_text, "time_text": ev.time_text, "precision": precision,
            "event": ev.event, "people": ev.people, "location": ev.location,
            "source": {"doc_id": doc["doc_id"], "person": doc["header"].get("name", ""),
                       "sentence_id": sid or ev.sentence_id, "quote": ev.evidence_quote},
            "verified": sid is not None})
    return events


def build_case_timeline(docs: list[dict]) -> list[dict]:
    events = [e for d in docs for e in extract_timeline(d)]
    # dated events first in chronological order, undated ones at the end
    events.sort(key=lambda e: (e["date"] is None, e["date"] or "", e["time"] or "99:99"))
    return events