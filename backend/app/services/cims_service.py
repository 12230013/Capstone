"""Authorization and structured reads for CIMS cases."""
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from fastapi import HTTPException

from app.database import connection
from app.services.presentation_access import (
    HAA_SCOPE, TOOL_SCOPE, presentation_scope, require_presentation_tool,
)

CASE_READ = "cims.case.read"
DOCUMENT_READ = "cims.document.read"
relationship_case_subjects = ContextVar("relationship_case_subjects", default=None)
SUBJECT_ACCESS = {
    "cdr": ("phone_number", "cims.cdr.read", 8),
    "relationships": ("cid", "cims.relationship.read", 11),
}


ROLE_CAPABILITIES = {
    "case_reader": frozenset({CASE_READ}),
    "document_reader": frozenset({CASE_READ, DOCUMENT_READ}),
    "investigator": frozenset({CASE_READ, DOCUMENT_READ, "cims.cdr.read", "cims.relationship.read"}),
}
logger = logging.getLogger(__name__)


def _store(collection):
    if collection is None:
        raise HTTPException(503, "Case service is unavailable.")
    return collection


def _grant(session, capability):
    grants = _store(connection.db["cims_access_grants"] if connection.db is not None else None)
    grant = grants.find_one({"_id": session["user_id"], "active": True})
    permissions = grant.get("permissions") if grant else None
    role = grant.get("role") if grant else None
    if (
        not isinstance(role, str) or capability not in ROLE_CAPABILITIES.get(role, ())
        or not isinstance(permissions, list) or capability not in permissions
    ):
        raise HTTPException(403, "Case access denied.")
    investigator = grant.get("investigator_id")
    if not isinstance(investigator, str) or not investigator.strip():
        raise HTTPException(403, "Case access denied.")
    return investigator


def _current_assignment(case_id):
    batches = _store(connection.cims_sync_collection)
    # Project authorization metadata only. Keep the batch identifier and array
    # position so subsequent reads cannot accidentally select another revision.
    rows = list(batches.aggregate([
        {"$match": {"cases.case_id": case_id}},
        {"$unwind": {"path": "$cases", "includeArrayIndex": "position"}},
        {"$match": {"cases.case_id": case_id}},
        {"$project": {
            "position": 1,
            "received_at": 1,
            "revision": "$cases.last_updated",
            "fingerprint": {"$arrayElemAt": ["$case_fingerprints", "$position"]},
            "investigators": "$cases.assigned_investigators",
        }},
    ]))
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    # The intake schema has day-level revisions. Where ordering is ambiguous,
    # require reconciliation instead of guessing which assignments are current.
    fingerprints = {row.get("fingerprint") for row in rows}
    if len(fingerprints) == 1 and None not in fingerprints:
        return rows[0]
    if any(not row.get("revision") for row in rows):
        return None
    latest = max(row["revision"] for row in rows)
    current = [row for row in rows if row["revision"] == latest]
    fingerprints = {row.get("fingerprint") for row in current}
    if len(current) == 1 or (len(fingerprints) == 1 and None not in fingerprints):
        return current[0]
    # Receipt order can choose between same-day records only when access would
    # be identical for every record. An assignment conflict still denies.
    investigators = current[0].get("investigators")
    if not investigators or any(
        row.get("investigators") != investigators or not row.get("received_at")
        for row in current
    ):
        return None
    newest = max(row["received_at"] for row in current)
    candidates = [row for row in current if row["received_at"] == newest]
    return candidates[0] if len(candidates) == 1 else None


def authorize_case(session, case_id, capability=CASE_READ):
    try:
        demo = presentation_scope(session)
        if demo is not None and demo.get("case_id") != case_id:
            raise HTTPException(403, "Case access denied.")
        investigator = _grant(session, capability)
        row = _current_assignment(case_id)
        investigators = row.get("investigators") if row else None
        if not isinstance(investigators, list) or investigator not in investigators:
            raise HTTPException(403, "Case access denied.")
    except HTTPException as exc:
        logger.info("CIMS case authorization rejected (%s, %s)", capability, exc.status_code)
        raise
    logger.info("CIMS case authorization granted (%s)", capability)
    return row


def read_case(session, case_id, fields):
    return read_case_fields(case_id, authorize_case(session, case_id), fields)


def read_case_fields(case_id, row, fields):
    batches = _store(connection.cims_sync_collection)
    projection = {field: f"$selected.{field}" for field in fields}
    projection["_id"] = 0
    result = next(iter(batches.aggregate([
        {"$match": {"_id": row["_id"]}},
        {"$set": {"selected": {"$arrayElemAt": ["$cases", row["position"]]}}},
        {"$match": {"selected.case_id": case_id}},
        {"$project": projection},
    ])), None)
    if result is None:
        raise HTTPException(403, "Case access denied.")
    return result


def list_cases(session):
    investigator = _grant(session, CASE_READ)
    batches = _store(connection.cims_sync_collection)
    candidates = batches.aggregate([
        {"$match": {"cases.assigned_investigators": investigator}},
        {"$unwind": "$cases"},
        {"$match": {"cases.assigned_investigators": investigator}},
        {"$group": {"_id": "$cases.case_id"}},
    ])
    cases = []
    for candidate in candidates:
        try:
            case = read_case(session, candidate["_id"], ("case_id", "case_title", "case_number"))
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
        else:
            cases.append(case)
    return sorted(cases, key=lambda case: case["case_id"])


CASE_REFERENCE = re.compile(
    r"\bcase\s+(?:(?:no\.?|number|id)\s*)?#?\s*"
    r"([a-z0-9]+(?:[-_/][a-z0-9]+)*)\b",
    re.IGNORECASE,
)


def _case_alias(value):
    return re.sub(r"^case[-_ ]+", "", str(value or "").strip().casefold())


def resolve_case_reference(session, query):
    references = {
        _case_alias(match)
        for match in CASE_REFERENCE.findall(query)
        if any(character.isdigit() for character in match)
    }
    if not references:
        return None
    if len(references) != 1:
        raise HTTPException(400, "Ask about one case at a time.")
    matches = [
        case["case_id"] for case in list_cases(session)
        if references.intersection({_case_alias(case["case_id"]), _case_alias(case.get("case_number"))})
    ]
    if len(matches) != 1:
        raise HTTPException(403, "This case could not be opened with your account.")
    return matches[0]


def infer_case_mode(query):
    if re.search(r"\b(?:cdr|call records?|call history|call summary|communication records?)\b", query, re.I):
        return ("cdr", _query_subject(query, 8))
    if re.search(r"\b(?:relationship mapping|relationships?|family tree|family members?)\b", query, re.I):
        return ("relationships", _query_subject(query, 11))
    if re.search(r"\b(?:in|from|summari[sz]e|read|quote|search)\s+(?:the\s+)?(?:case\s+)?(?:documents?|files?|pdf|docx)\b|\.(?:pdf|docx)\b", query, re.I):
        return ("documents", None)
    return ("metadata", None)


def _query_subject(query, digits):
    subjects = set(re.findall(rf"(?<![0-9])[0-9]{{{digits}}}(?![0-9])", CASE_REFERENCE.sub("", query)))
    if len(subjects) != 1:
        raise HTTPException(400, f"Include one {digits}-digit subject identifier in your question.")
    return subjects.pop()


def authorize_subject(session, case_id, mode, subject):
    field, capability, digits = SUBJECT_ACCESS[mode]
    if not isinstance(subject, str) or not re.fullmatch(rf"[0-9]{{{digits}}}", subject):
        raise HTTPException(403, "Case access denied.")
    if case_id == TOOL_SCOPE:
        require_presentation_tool(session, mode)
        return None
    row = authorize_case(session, case_id, capability)
    entities = read_case_fields(case_id, row, ("entities",)).get("entities") or []
    allowed = set()
    for entity in entities:
        identifier = entity.get(field)
        if not isinstance(identifier, str):
            continue
        identifier = identifier.strip()
        if mode == "cdr":
            identifier = identifier.removeprefix("+975")
        if re.fullmatch(rf"[0-9]{{{digits}}}", identifier):
            allowed.add(identifier)
    if subject not in allowed:
        raise HTTPException(403, "Case access denied.")
    return frozenset(allowed)


@contextmanager
def relationship_scope(subjects):
    token = relationship_case_subjects.set(subjects)
    try:
        yield
    finally:
        relationship_case_subjects.reset(token)


def authorize_conversation_scope(session, conversation):
    case_id = conversation.get("case_id")
    mode = conversation.get("case_mode", "metadata")
    demo = presentation_scope(session)
    if case_id == HAA_SCOPE:
        if demo is None or demo.get("case_id") != HAA_SCOPE or mode != "metadata":
            raise HTTPException(403, "Case access denied.")
        return
    if case_id == TOOL_SCOPE:
        if mode not in SUBJECT_ACCESS:
            raise HTTPException(403, "Tool access denied.")
        authorize_subject(session, case_id, mode, conversation.get("case_subject"))
        return
    if demo is not None and case_id != demo.get("case_id"):
        raise HTTPException(403, "Case access denied.")
    if case_id is not None:
        authorize_case(session, case_id)
        if mode == "documents":
            authorize_case(session, case_id, DOCUMENT_READ)
        elif mode in SUBJECT_ACCESS:
            authorize_subject(session, case_id, mode, conversation.get("case_subject"))
        elif mode != "metadata":
            raise HTTPException(403, "Case access denied.")


def case_visible(session, conversation):
    try:
        authorize_conversation_scope(session, conversation)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return False
    return True


CASE_OVERVIEW_FIELDS = (
    "case_number", "case_title", "case_status", "registered_date",
    "allegation_details", "entities", "case_events",
)

CASE_QUESTION_FIELDS = (
    (r"\b(?:assigned investigators?|case officers?|who (?:is|was) (?:assigned|investigating))\b", "assigned_investigators"),
    (r"\b(?:interviews?|statements?|testimony|interviewed)\b", "interviews"),
    (r"\b(?:allegations?|accused of|what is alleged)\b", "allegation_details"),
    (r"\b(?:timeline|events?|chronology|what happened|when did it happen)\b", "case_events"),
    (r"\b(?:who|people|persons?|entities|entity|subjects?|involv(?:ed|ement)|suspects?|witnesses?|parties)\b", "entities"),
    (r"\b(?:documents?|files?|attachments?)\b", "documents"),
    (r"\b(?:status|open|closed)\b", "case_status"),
    (r"\b(?:registered|registration date|filed)\b", "registered_date"),
    (r"\bcase (?:number|no\.)\b", "case_number"),
    (r"\b(?:case title|case name)\b", "case_title"),
)

CASE_FIELD_LABELS = {
    "allegation_details": "Recorded allegations",
    "entities": "People and entities recorded in the case",
    "case_events": "Recorded events",
}


def _case_question_fields(query):
    fields = tuple(field for pattern, field in CASE_QUESTION_FIELDS if re.search(pattern, query, re.I))
    if fields:
        return fields
    if re.search(r"\b(?:summari[sz]e|summary|overview|tell me about|explain|case details|what (?:is|was) (?:it|this case) about)\b", query, re.I):
        return CASE_OVERVIEW_FIELDS
    return ()


def _render_case_items(field, items):
    if field == "entities":
        return [
            " — ".join(filter(None, (item.get("name") or "Name unavailable", item.get("entity_type"), item.get("involvement"))))
            for item in items
        ]
    if field == "case_events":
        return [
            " — ".join(filter(None, (item.get("event_date"), item.get("event_name") or "Event", item.get("description"))))
            for item in sorted(items, key=lambda item: item.get("event_date") or "9999")
        ]
    return [
        ", ".join(
            f"{key.replace('_', ' ')}: {entry if entry is not None else 'Unavailable'}"
            for key, entry in item.items()
        ) if isinstance(item, dict) else str(item)
        for item in items
    ]


def case_metadata_passages(session, case_id, question):
    fields = _case_question_fields(question) or CASE_OVERVIEW_FIELDS
    record = read_case(session, case_id, fields)
    passages = {}
    for field in fields:
        value = record.get(field)
        if value is None or value == []:
            continue
        label = CASE_FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
        if isinstance(value, list):
            value = "\n".join(_render_case_items(field, value))
        passages[field] = f"{label}: {value}"
    return passages


def answer_case_query(session, case_id, query):
    fields = _case_question_fields(query)
    if not fields:
        authorize_case(session, case_id)
        return {"success": True, "response": {
            "answer": "I couldn't match that question to a CIMS case field. You can ask for a summary, allegations, people involved, a timeline, interviews, documents, or status.",
            "sources": [],
        }}

    record = read_case(session, case_id, fields)
    lines = []
    for field in fields:
        label = CASE_FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
        value = record.get(field)
        if value is None or value == []:
            lines.append(f"**{label}** — Unavailable")
        elif isinstance(value, list):
            items = "\n".join(f"- {item}" for item in _render_case_items(field, value))
            lines.append(f"**{label}**\n{items}")
        else:
            lines.append(f"**{label}** — {value}")
    return {
        "success": True,
        "response": {
            "answer": "\n\n".join(lines),
            "sources": [{"type": "CIMS case metadata", "case_id": case_id}],
        },
    }
