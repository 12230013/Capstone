from app.services.evidence_grounding import answer_from_evidence, numbered_sentences
from starlette.concurrency import run_in_threadpool
from datetime import date, datetime
from pyexpat.errors import messages
import re
import json
from typing import Any, Optional

from opentelemetry import context

from app.services.rag_service import RAGService
from app.services.cdr_service import CDRService
from app.services.llm_service import LLMService
from app.services.prompt_service import PromptService

from app.api.routes.relationship import (
    get_relationships,
    relationship_visualization,
)

from app.analytics.cdr_analytics import (
    analyze_communication_frequency,
    analyze_communication_direction,
    analyze_period_statistics,
    generate_communication_timeline,
    analyze_interactions,
    detect_irregular_patterns,
    generate_communication_network,
)


# =============================================================
# General helpers
# =============================================================

def _get(value: Any, key: str, default=None):
    """Read a field from either a dictionary or a model object."""
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _as_datetime(value: Any) -> Optional[datetime]:
    """Convert a datetime or ISO-formatted datetime string."""
    if isinstance(value, datetime):
        return value

    if not isinstance(value, str) or not value.strip():
        return None

    try:
        return datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )
    except ValueError:
        return None


def _parse_clock(hour: int, minute: int, meridiem: Optional[str]):
    """Convert a 12-hour or 24-hour clock value to minutes after midnight."""
    if minute < 0 or minute > 59:
        return None

    if meridiem:
        meridiem = meridiem.lower().replace(".", "")

        if hour < 1 or hour > 12:
            return None

        hour = hour % 12
        if meridiem == "pm":
            hour += 12
    elif hour < 0 or hour > 23:
        return None

    return hour * 60 + minute


def parse_time_range(query: str):
    """
    Recognize ranges such as:
      12 AM to 6 AM
      10 PM to 2 AM
      midnight to 6 in the morning
      22:00 to 06:00

    Returns (start_minutes, end_minutes), or None.
    The end is exclusive when filtering records.
    """
    text = query.lower()

    # Convert common natural-language clock descriptions.
    text = re.sub(r"\bmidnight\b", "12:00 am", text)
    text = re.sub(r"\bnoon\b", "12:00 pm", text)

    pattern = re.compile(
        r"(?<![\d:])"
        r"(\d{1,2})"
        r"(?::(\d{2}))?"
        r"\s*(a\.?m\.?|p\.?m\.?)?"
        r"\s*(?:to|and|through|until|[-–])\s*"
        r"(\d{1,2})"
        r"(?::(\d{2}))?"
        r"\s*(a\.?m\.?|p\.?m\.?)?"
        r"(?!\d)",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    # Do not treat arbitrary number ranges as times unless the query
    # provides a clock indicator or a time-of-day expression.
    has_time_context = bool(
        re.search(
            r"\b(am|pm|morning|afternoon|evening|night|midnight|noon|"
            r"o'clock|hours?|between|from)\b",
            query,
            re.IGNORECASE,
        )
        or re.search(r"\b\d{1,2}:\d{2}\b", query)
    )

    if not match or not has_time_context:
        return None

    h1, m1, ap1, h2, m2, ap2 = match.groups()

    h1 = int(h1)
    m1 = int(m1 or 0)
    h2 = int(h2)
    m2 = int(m2 or 0)

    ap1 = (ap1 or "").replace(".", "").lower() or None
    ap2 = (ap2 or "").replace(".", "").lower() or None

    # Infer a missing AM/PM suffix from the other endpoint or wording.
    if not ap1 and ap2:
        ap1 = ap2
    elif not ap2 and ap1:
        ap2 = ap1
    elif not ap1 and not ap2:
        if re.search(r"\b(morning|midnight)\b", query, re.I):
            ap1 = ap2 = "am"
        elif re.search(r"\b(afternoon|evening|night)\b", query, re.I):
            ap1 = ap2 = "pm"
        else:
            # Plain 24-hour clock values, such as 22:00 to 06:00.
            if ":" not in match.group(0):
                return None

    start = _parse_clock(h1, m1, ap1)
    end = _parse_clock(h2, m2, ap2)

    if start is None or end is None or start == end:
        return None

    return start, end


def _in_time_range(dt: datetime, start: int, end: int) -> bool:
    """Support both ordinary and overnight time ranges."""
    current = dt.hour * 60 + dt.minute

    if start < end:
        return start <= current < end

    # Example: 10 PM to 2 AM.
    return current >= start or current < end


def _format_duration(seconds: Any) -> str:
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        return "Unknown"

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)

def _table_cell(value: Any) -> str:
    """Make values safe to display inside a Markdown table."""
    if value is None or str(value).strip() == "":
        return "Unknown"

    return (
        str(value)
        .replace("|", "\\|")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _format_record_table_row(record: Any) -> str:
    dt = _as_datetime(_get(record, "datetime"))
    datetime_text = (
        dt.strftime("%Y-%m-%d %H:%M:%S")
        if dt
        else str(_get(record, "datetime", "Unknown"))
    )

    calling = _get(record, "calling_number", "Unknown")
    called = _get(record, "called_number", "Unknown")

    calling_name = (
        _get(record, "calling_party_name")
        or _get(record, "calling_name")
    )
    called_name = (
        _get(record, "called_party_name")
        or _get(record, "called_name")
    )

    if calling_name:
        calling = f"{calling} ({calling_name})"
    if called_name:
        called = f"{called} ({called_name})"

    duration = _get(record, "duration_seconds")
    if duration is None:
        duration = _get(record, "duration", 0)

    return (
        f"| {_table_cell(datetime_text)} "
        f"| {_table_cell(calling)} "
        f"| {_table_cell(called)} "
        f"| {_table_cell(_get(record, 'service', 'Unknown'))} "
        f"| {_table_cell(_format_duration(duration))} |"
    )

def _format_record(record: Any) -> str:
    """Format a CDR record without inventing missing information."""
    dt = _as_datetime(_get(record, "datetime"))

    datetime_text = (
        dt.isoformat(sep=" ", timespec="seconds")
        if dt
        else str(_get(record, "datetime", "Unknown"))
    )

    calling = _get(record, "calling_number", "Unknown")
    called = _get(record, "called_number", "Unknown")

    calling_name = (
        _get(record, "calling_party_name")
        or _get(record, "calling_name")
        or ""
    )
    called_name = (
        _get(record, "called_party_name")
        or _get(record, "called_name")
        or ""
    )

    duration = _get(record, "duration_seconds")
    if duration is None:
        duration = _get(record, "duration", 0)

    service = _get(record, "service", "Unknown")

    return (
        f"- **Date/time:** {datetime_text}\n"
        f"  - **Calling number:** {calling}"
        f"{f' ({calling_name})' if calling_name else ''}\n"
        f"  - **Called number:** {called}"
        f"{f' ({called_name})' if called_name else ''}\n"
        f"  - **Service:** {service}\n"
        f"  - **Duration:** {_format_duration(duration)}"
    )


# =============================================================
# Relationship answer formatting
# =============================================================

def format_relationship_answer(data: dict, query: str) -> str:
    query_lower = query.lower()

    def person_label(person):
        name = (
            _get(person, "fullName")
            or _get(person, "name")
            or "Unknown"
        )
        cid = _get(person, "cid") or _get(person, "id") or "Unknown"
        return f"{name} with CID {cid}"

    target = data.get("target", {})
    lines = [f"The target person is {person_label(target)}."]
    relationships = data.get("relationships", [])

    def get_people(relation_type):
        return [
            item for item in relationships
            if item.get("type") == relation_type
        ]

    def format_people(items):
        if not items:
            return ["No information available."]

        return [
            f"{i}. On the {item.get('side', 'UNKNOWN')} side: "
            f"{person_label(item.get('person', {}))}."
            for i, item in enumerate(items, 1)
        ]

    asks_parents = bool(
        re.search(r"\b(parent|parents|father|mother)\b", query_lower)
    )
    asks_siblings = bool(
        re.search(r"\b(sibling|siblings|brother|sister)\b", query_lower)
    )
    asks_spouse_side = bool(
        re.search(
            r"\bspouse[- ]side\b|\bside of the spouse\b",
            query_lower,
        )
    )
    asks_target_side = bool(
        re.search(
            r"\btarget[- ]side\b|\btarget's side\b",
            query_lower,
        )
    )
    asks_first_degree = bool(
        re.search(
            r"\b(first|1st)[-\s]+degree\b|\bdegree\s*1\b",
            query_lower,
        )
    )
    asks_complete_tree = any(
        phrase in query_lower
        for phrase in (
            "complete family tree",
            "full family tree",
            "all relationships",
            "all degrees",
            "show the family tree",
            "visualize the family tree",
            "visualise the family tree",
        )
    )

    if (asks_parents or asks_siblings) and not asks_complete_tree:

        def filter_by_side(items):
            if asks_spouse_side:
                return [x for x in items if x.get("side") == "SPOUSE"]
            if asks_target_side:
                return [x for x in items if x.get("side") == "TARGET"]
            return items

        if asks_parents:
            label = (
                "The spouse-side parents are:"
                if asks_spouse_side
                else "The target-side parents are:"
                if asks_target_side
                else "The parents are:"
            )
            lines.extend(["", label])
            lines.extend(format_people(filter_by_side(get_people("PARENT"))))

        if asks_siblings:
            label = (
                "The spouse-side siblings are:"
                if asks_spouse_side
                else "The target-side siblings are:"
                if asks_target_side
                else "The siblings are:"
            )
            lines.extend(["", label])
            lines.extend(format_people(filter_by_side(get_people("SIBLING"))))

        return "\n".join(lines)

    if asks_first_degree or (
        not asks_complete_tree
        and not asks_parents
        and not asks_siblings
        and int(data.get("degree", 1)) == 1
    ):
        for label, key in (("Spouse(s)", "spouses"), ("Children", "children")):
            lines.extend(["", f"{label}:"])
            people = data.get(key, [])
            if people:
                lines.extend(
                    f"{i}. {person_label(person)}."
                    for i, person in enumerate(people, 1)
                )
            else:
                lines.append(f"No {label.lower()} information available.")

        return "\n".join(lines)

    for label, key in (("Spouse(s)", "spouses"), ("Children", "children")):
        lines.extend(["", f"{label}:"])
        people = data.get(key, [])
        if people:
            lines.extend(
                f"{i}. {person_label(person)}."
                for i, person in enumerate(people, 1)
            )
        else:
            lines.append(f"No {label.lower()} information available.")

    for label, relation_type in (("Parents", "PARENT"), ("Siblings", "SIBLING")):
        lines.extend(["", f"{label}:"])
        lines.extend(format_people(get_people(relation_type)))

    lines.extend(["", "Extended family:"])
    for family in data.get("siblingFamilies", []):
        sibling = family.get("sibling", {})
        lines.append(
            f"\nFamily of {person_label(sibling)} "
            f"(side: {family.get('side', 'UNKNOWN')}):"
        )
        for spouse in family.get("spouses", []):
            lines.append(f"- Spouse: {person_label(spouse)}.")
        for child in family.get("children", []):
            lines.append(f"- Child: {person_label(child)}.")

    return "\n".join(lines)


# =============================================================
# Chat service
# =============================================================

class ChatService:
    def __init__(self):
        self._rag_service = None
        self._cdr_service = None
        self._llm_service = None
        self._prompt_service = None
        self._statement_service = None

    @property
    def rag_service(self):
        if self._rag_service is None:
            self._rag_service = RAGService()
        return self._rag_service

    @property
    def cdr_service(self):
        if self._cdr_service is None:
            self._cdr_service = CDRService()
        return self._cdr_service

    @property
    def llm_service(self):
        if self._llm_service is None:
            self._llm_service = LLMService()
        return self._llm_service

    @property
    def prompt_service(self):
        if self._prompt_service is None:
            self._prompt_service = PromptService()
        return self._prompt_service

    @property
    def statement_service(self):
        if self._statement_service is None:
            from app.services.statement_service import StatementService
            self._statement_service = StatementService()
        return self._statement_service

    @staticmethod
    def _response(answer, sources=None, **extra):
        response = {
            "answer": answer,
            "sources": sources or [],
        }
        response.update(extra)
        return {"success": True, "response": response}

    @staticmethod
    def _source(number, analysis):
        return {
            "type": "CDR analysis",
            "phone_number": number,
            "analysis": analysis,
        }

    #mine
    @staticmethod
    def _requested_evidence_systems(query_lower: str) -> set:
        """Identify evidence systems explicitly mentioned in a query."""
        systems = set()

        statement_terms = (
            "statement", "statements", "witness", "testimony",
            "accused said", "person said", "case", "investigation", "accused", "case evidence"
        )
        cdr_terms = (
            "cdr","call record","call records","call log","call logs","phone record", "phone records",
            "phone number","call history","communication record","communication records", "incoming",
            "outgoing","call frequency","call interactions",
        )
        relationship_terms = (
            "family tree", "family relationship",
            "relationship records", "relatives", "family members", "family tree for"
        )

        if any(term in query_lower for term in statement_terms):
            systems.add("statements")

        if any(term in query_lower for term in cdr_terms):
            systems.add("cdr")

        if any(term in query_lower for term in relationship_terms):
            systems.add("relationships")

        return systems

    async def _handle_combined_query(self, query: str) -> dict:
        """
        Retrieve evidence from explicitly requested systems and generate
        one answer from the combined evidence.
        """
        query_lower = query.lower()
        requested = self._requested_evidence_systems(query_lower)

        evidence = []
        #mine
        # for hit in hits:
        #     text_numbered = hit.get("text_numbered", "")

        #     # Extract individually cited sentences where possible.
        #     sentence_matches = re.findall(
        #         r"(?m)^\s*(?:[-*]\s*)?"
        #         r"\[?([A-Za-z0-9_-]+-s\d+)\]?"
        #         r"\s*[:.)-]?\s*(.+?)\s*$",
        #         text_numbered,
        #     )

        #     if sentence_matches:
        #         for sentence_id, sentence_text in sentence_matches:
        #             evidence.append({
        #                 "source_type": "statement_sentence",
        #                 "source_id": sentence_id,
        #                 "statement_id": hit.get("doc_id"),
        #                 "person_name": hit.get("person_name"),
        #                 "statement_date": hit.get("statement_date"),
        #                 "case_no": hit.get("case_no"),
        #                 "retrieval_score": hit.get("score"),
        #                 "text": sentence_text,
        #             })
        #     else:
        #         # Preserve the original text if its sentence format differs.
        #         evidence.append({
        #             "source_type": "statement_chunk",
        #             "source_id": hit.get("doc_id"),
        #             "statement_id": hit.get("doc_id"),
        #             "person_name": hit.get("person_name"),
        #             "statement_date": hit.get("statement_date"),
        #             "case_no": hit.get("case_no"),
        #             "retrieval_score": hit.get("score"),
        #             "text": text_numbered,
        #         })

        warnings = []
        sources_used = []

        # ---------------------------------------------------------
        # Statement evidence: retrieval only, no separate answer.
        # ---------------------------------------------------------
        if "statements" in requested:
            try:
                result = (
                    self.statement_service.retrieve_statement_evidence(
                        query=query
                    )
                )
                print("STATEMENT RETRIEVAL SUCCESS:", result.get("success"))
                print(
                    "STATEMENT EVIDENCE COUNT:",
                    len(result.get("evidence", [])),
                )
                print("STATEMENT WARNINGS:", result.get("warnings", []))

                if result.get("success"):
                    for item in result.get("evidence", []):
                        evidence.append({
                            "source_type": "statement",
                            "source_id": item.get("statement_id"),
                            "person_name": item.get("person_name"),
                            "statement_date": item.get("statement_date"),
                            "case_no": item.get("case_no"),
                            "retrieval_score": item.get("retrieval_score"),
                            "text": item.get("text", ""),
                        })

                    warnings.extend(result.get("warnings", []))
                    if result.get("evidence"):
                        sources_used.append("statements")
                else:
                    warnings.append(
                        "Statement evidence could not be retrieved."
                    )

            except Exception as exc:
                print(f"Combined statement retrieval error: {exc}")
                warnings.append(
                    "Statement evidence could not be retrieved."
                )

        # ---------------------------------------------------------
        # CDR evidence: preserve individual call records.
        # ---------------------------------------------------------
        if "cdr" in requested:
            numbers = re.findall(
                r"(?<!\d)[0-9]{8}(?!\d)",
                query,
            )

            if not numbers:
                warnings.append(
                    "CDR evidence was requested, but no valid "
                    "8-digit target phone number was identified."
                )
            else:
                number = numbers[0]

                try:
                    summary = await self.cdr_service.get_summary(number)

                    for index, record in enumerate(
                        summary.records or [], start=1
                    ):
                        evidence.append({
                            "source_type": "cdr_record",
                            "source_id": (
                                f"cdr:{number}:"
                                f"{_get(record, 'datetime', 'unknown')}:"
                                f"{index}"
                            ),
                            "target_number": number,
                            "datetime": str(
                                _get(record, "datetime", "Unknown")
                            ),
                            "calling_number": _get(
                                record, "calling_number"
                            ),
                            "called_number": _get(
                                record, "called_number"
                            ),
                            "called_party_name": _get(
                                record, "called_party_name"
                            ),
                            "called_party_cid": _get(
                                record, "called_party_cid"
                            ),
                            "service": _get(record, "service"),
                            "duration": _get(record, "duration"),
                            "duration_seconds": _get(
                                record, "duration_seconds"
                            ),
                        })

                    if summary.records:
                        sources_used.append("cdr")

                except Exception as exc:
                    print(f"Combined CDR retrieval error: {exc}")
                    warnings.append(
                        "CDR evidence could not be retrieved."
                    )

        # ---------------------------------------------------------
        # Relationship evidence: preserve relationship fields.
        # ---------------------------------------------------------
        if "relationships" in requested:
            cid_match = re.search(
                r"(?<!\d)[0-9]{11}(?!\d)",
                query,
            )

            if not cid_match:
                warnings.append(
                    "Relationship evidence was requested, but no "
                    "valid 11-digit CID was identified."
                )
            else:
                cid = cid_match.group(0)

                degree = "1"

                if re.search(
                    r"\b(?:third|3rd)[-\s]+degree\b"
                    r"|\bdegree\s*3\b"
                    r"|\ball degrees\b"
                    r"|\bcomplete family tree\b"
                    r"|\bfull family tree\b"
                    r"|\bfamily tree\b"
                    r"|\brelationship network\b",
                    query_lower,
                ):
    
                    degree = "3"
                elif re.search(
                    r"\b(?:second|2nd)[-\s]+degree\b|\bdegree\s*2\b",
                    query_lower,
                ):
                    degree = "2"

                try:
                    data = await get_relationships(
                        cid=cid,
                        degree=degree,
                    )

                    target = data.get("target", {})
                    evidence.append({
                        "source_type": "relationship_target",
                        "source_id": f"relationship:{cid}:target",
                        "cid": _get(target, "cid", cid),
                        "person_name": _get(
                            target, "fullName",
                            _get(target, "name", "Unknown"),
                        ),
                        "degree_requested": int(degree),
                    })

                    for index, relation in enumerate(
                        data.get("relationships", []), start=1
                    ):
                        person = relation.get("person", {})

                        evidence.append({
                            "source_type": "relationship_record",
                            "source_id": (
                                f"relationship:{cid}:{index}"
                            ),
                            "target_cid": cid,
                            "related_cid": _get(
                                person, "cid",
                                _get(person, "id"),
                            ),
                            "related_person": _get(
                                person, "fullName",
                                _get(person, "name", "Unknown"),
                            ),
                            "relationship_type": relation.get("type"),
                            "side": relation.get("side"),
                            "degree_requested": int(degree),
                        })

                    sources_used.append("relationships")

                except Exception as exc:
                    print(f"Combined relationship retrieval error: {exc}")
                    warnings.append(
                        "Relationship evidence could not be retrieved."
                    )

        # ---------------------------------------------------------
        # Build one evidence-grounded prompt for the main LLM.
        # ---------------------------------------------------------
        if not evidence:
            return self._response(
                "I don't have information for this comparison in the available records. "
                "Check the identifiers and the availability of the "
                "requested source systems.",
                [],
                warnings=warnings,
            )

        supported_records = {}
        for index, item in enumerate(evidence, start=1):
            sentences = numbered_sentences(item.get("text", ""))
            if sentences:
                supported_records.update(sentences)
            else:
                source_id = str(item.get("source_id") or f"record_{index}")
                supported_records[source_id] = json.dumps(item, ensure_ascii=False, default=str)

        try:
            grounded = await run_in_threadpool(
                answer_from_evidence, query, supported_records, self.llm_service.generate
            )
            answer = grounded["answer"]
            if warnings:
                answer += "\n\nSome requested sources were unavailable. This answer uses only the retrieved records."
        except Exception as exc:
            print(f"Combined evidence generation error: {exc}")
            return self._response(
                "I retrieved evidence but couldn't generate the combined "
                "analysis. Please try again.",
                [],
                warnings=warnings,
            )

        return self._response(
            answer,
            [
                {
                    "type": "Combined Evidence",
                    "systems": sources_used,
                    "evidence_count": len(evidence),
                }
            ] if grounded["has_information"] else [],
            evidence=evidence,
            warnings=warnings,
        )

    async def _handle_relationship_query(self, query, query_lower, cid):
        # Reject unsupported degrees instead of silently using degree 1.
        unsupported_degree = re.search(
            r"\b(?:fourth|4th)[-\s]*degree\b"
            r"|\bdegree\s*(?:4|four)\b",
            query_lower,
        )

        if unsupported_degree:
            return self._response(
                "Unsupported relationship degree. "
                "Only degrees 1, 2, and 3 are supported."
            )
        
        degree = "1"

        if re.search(
            r"\b(?:all degrees|all relationships|complete family tree|full family tree| family tr relationship networkee |)\b",
            query_lower,
        ):
            degree = "3"
        elif re.search(
            r"\b(?:third|3rd)[-\s]+degree\b|\bdegree\s*3\b",
            query_lower,
        ):
            degree = "3"
        elif re.search(
            r"\b(?:second|2nd)[-\s]+degree\b|\bdegree\s*2\b",
            query_lower,
        ):
            degree = "2"
        elif re.search(
            r"\b(?:first|1st)[-\s]+degree\b|\bdegree\s*1\b",
            query_lower,
        ):
            degree = "1"
        elif re.search(
            r"\b(parent|parents|father|mother|sibling|siblings|brother|sister)\b",
            query_lower,
        ):
            degree = "2"

        try:
            relationship_data = await get_relationships(
                cid=cid,
                degree=degree,
            )

            answer = format_relationship_answer(relationship_data, query)

            visualization_keywords = [
                "complete family tree",
                "full family tree",
                "show the family tree",
                "show me the family tree",
                "display the family tree",
                "visualize the family tree",
                "visualise the family tree",
                "show the relationship network",
                "display the relationship network",
                "visualize relationships",
                "visualise relationships",
                "visualize the relationships",
                "visualise the relationships",
                "map the relationships",
                "show me the relationship map",
            ]

            response = {
                "answer": answer,
                "sources": [{
                    "type": "Relationship Mapping API",
                    "cid": cid,
                    "degree": int(degree),
                }],
            }

            if any(phrase in query_lower for phrase in visualization_keywords):
                visualization_data = await relationship_visualization(
                    cid=cid,
                    degree=degree,
                )
                response["visualization"] = {
                    "type": "relationship_network",
                    "data": visualization_data,
                }

            return {"success": True, "response": response}

        except Exception as exc:
            print(f"Relationship query error: {exc}")
            return {
                "success": False,
                "response": {
                    "answer": (
                        "I couldn't retrieve relationship information for "
                        "this person. Please verify the CID and try again."
                    ),
                    "sources": [],
                },
            }

    async def _handle_cdr_query(self, query, query_lower, number):
        summary = await self.cdr_service.get_summary(number)
        records = list(summary.records or [])

        contact_match = re.search(r"\bcontact(?:\s+number)?\s*[:=]?\s*([0-9]{8})(?!\d)", query, re.I)
        contact = contact_match.group(1) if contact_match else None
        outgoing = bool(re.search(r"\boutgoing\b", query_lower))
        incoming = bool(re.search(r"\bincoming\b", query_lower))
        if contact or outgoing != incoming:
            records = [record for record in records if (
                (str(_get(record, "calling_number")) == number and
                 (not contact or str(_get(record, "called_number")) == contact))
                if outgoing and not incoming else
                (str(_get(record, "called_number")) == number and
                 (not contact or str(_get(record, "calling_number")) == contact))
                if incoming and not outgoing else
                ({str(_get(record, "calling_number")), str(_get(record, "called_number"))} == {number, contact})
            )]

        # Explicit time ranges take priority over pattern detection.
        time_range = parse_time_range(query)
        date_values = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", query)

        if time_range:
            start_minutes, end_minutes = time_range
            filtered_records = []

            # If the user also supplied two dates, apply both filters.
            start_date = end_date = None
            if len(date_values) >= 2:
                start_date = date.fromisoformat(date_values[0])
                end_date = date.fromisoformat(date_values[1])

                if end_date < start_date:
                    raise ValueError("The end date must not precede the start date.")

            unparseable_count = 0

            for record in records:
                dt = _as_datetime(_get(record, "datetime"))

                if dt is None:
                    unparseable_count += 1
                    continue

                if start_date and not (start_date <= dt.date() <= end_date):
                    continue

                if _in_time_range(dt, start_minutes, end_minutes):
                    filtered_records.append(record)

            time_label = (
                f"{start_minutes // 60:02d}:{start_minutes % 60:02d} to "
                f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
            )

            if not filtered_records:
                answer = (
                    f"No communication records for {number} matched the "
                    f"requested time range ({time_label})."
                )
                if not records:
                    answer += " The CDR service returned no records."
                elif unparseable_count == len(records):
                    answer += (
                        " The returned records did not contain parseable "
                        "datetime values, so the time filter could not be applied."
                    )

                return self._response(
                    answer,
                    [self._source(number, "time_range_records")],
                )

            filtered_records.sort(
                key=lambda record: _as_datetime(_get(record, "datetime"))
            )

            lines = [
                f"## Communication records for {number}",
                f"**Time range:** {time_label}",
                f"**Matching records:** {len(filtered_records)}",
            ]
            if contact:
                lines.append(f"**Contact:** {contact}")
            if outgoing != incoming:
                lines.append(f"**Direction:** {'Outgoing' if outgoing else 'Incoming'}")

            if start_date and end_date:
                lines.append(
                    f"**Date range:** {start_date.isoformat()} to "
                    f"{end_date.isoformat()}"
                )

            lines.extend([
                "",
                "| Date and time | Calling number | Called number | Service | Duration |",
                "|---|---|---|---|---:|",
            ])

            lines.extend(
                _format_record_table_row(record)
                for record in filtered_records
            )

            if unparseable_count:
                lines.extend([
                    "",
                    f"Note: {unparseable_count} record(s) were excluded because "
                    "their datetime could not be parsed.",
                ])

            return self._response(
                "\n".join(lines),
                [self._source(number, "time_range_records")],
            )

        # ---------------------------------------------------------
        # Intent detection
        # ---------------------------------------------------------

        is_unusual_hours_query = bool(
            re.search(
                r"\b(unusual|odd|late[- ]night|early[- ]morning)\b"
                r".{0,40}\b(hours?|communication|communications|calls?)\b"
                r"|\b(unusual|odd)\s+communication\s+hours\b"
                r"|\b(calls?|communications?)\b.{0,40}"
                r"\b(during|between)\b.{0,30}\b(unusual|late[- ]night)\b",
                query_lower,
            )
        )

        is_all_patterns_query = any(
            phrase in query_lower
            for phrase in (
                "all patterns",
                "all communication patterns",
                "all irregular patterns",
                "all anomalies",
                "analyze everything",
            )
        )

        
        # Identify a specific irregular pattern when the user asks for one.
        requested_pattern_type = None

        if is_unusual_hours_query or (
            re.search(r"\bunusual\s+communication\b", query_lower)
            and not re.search(r"\bpatterns?\b", query_lower)
        ):
            requested_pattern_type = "UNUSUAL_COMMUNICATION_HOURS"

        elif re.search(
            r"\b(repeated short calls?|short calls?|brief calls?)\b",
            query_lower,
        ):
            requested_pattern_type = "REPEATED_SHORT_CALLS"

        elif re.search(
            r"\b(high[- ]frequency|frequent contacts?|most frequent contacts?)\b",
            query_lower,
        ):
            requested_pattern_type = "HIGH_FREQUENCY"

        elif re.search(
            r"\bone[- ]sided incoming\b|\bmostly incoming\b",
            query_lower,
        ):
            requested_pattern_type = "ONE_SIDED_INCOMING"

        elif re.search(
            r"\bone[- ]sided outgoing\b|\bmostly outgoing\b",
            query_lower,
        ):
            requested_pattern_type = "ONE_SIDED_OUTGOING"

        elif re.search(
            r"\b(communication spikes?|call spikes?|spikes in communication)\b",
            query_lower,
        ):
            requested_pattern_type = "COMMUNICATION_SPIKE"


        is_irregular_query = (
            requested_pattern_type is not None
            or any(
                word in query_lower
                for word in ("irregular", "suspicious", "unusual", "anomal")
            )
        )


        is_network_query = any(
            phrase in query_lower
            for phrase in (
                "communication network",
                "network graph",
                "call network",
                "network",
            )
        )

        is_timeline_query = any(
            phrase in query_lower
            for phrase in (
                "communication timeline",
                "call timeline",
                "communication history",
                "call history",
                "history of communication",
                "timeline",
            )
        )

        is_interactions_query = any(
            phrase in query_lower
            for phrase in (
                "interactions with",
                "interaction with",
                "interactions for",
                "interaction for",
                "interactions of",
                "interaction of",
                "show me the interactions",
                "interaction details",
                "contact interactions",
                "communicated with",
                "communication with",
            )
        )

        summary_indicators = (
            "summary",
            "summarize",
            "overview",
            "communication activity",
            "overall communication",
            "overall activity",
            "comprehensive",
        )

        requested_statistics = (
            "total interactions",
            "incoming",
            "outgoing",
            "total duration",
            "most frequent",
            "frequency",
        )

        statistic_count = sum(
            phrase in query_lower for phrase in requested_statistics
        )

        is_general_summary_query = (
            any(word in query_lower for word in summary_indicators)
            or statistic_count >= 2
        )

        is_frequency_query = any(
            phrase in query_lower
            for phrase in (
                "communication frequency",
                "call frequency",
                "frequent contacts",
                "most frequent contacts",
                "most frequent",
                "most contacted",
                "top contacts",
                "frequency",
            )
        )

        has_incoming_term = any(term in query_lower for term in ("incoming", "inbound"))
        has_outgoing_term = any(term in query_lower for term in ("outgoing", "outbound"))
        has_direction_term = has_incoming_term or has_outgoing_term
        asks_to_list_calls = any(
            term in query_lower for term in ("show", "list", "display", "retrieve", "get")
        )
        has_call_records_term = any(
            term in query_lower for term in ("call", "calls", "communication records", "communications")
        )
        is_call_list_query = (
            asks_to_list_calls
            and has_call_records_term
            and has_direction_term
            and not any(term in query_lower for term in ("compare", "comparison", "timeline", "network"))
        )
        is_direction_query = any(
            phrase in query_lower
            for phrase in (
                "communication direction",
                "call direction",
                "direction",
            )
        ) or (has_incoming_term and has_outgoing_term)

        comparison_intent = any(
            term in query_lower
            for term in ("compare", "comparison", "which direction", "more interactions", "more calls")
        )

        # A request comparing incoming and outgoing counts is focused, even if
        # the wording contains broad CDR terms such as "communication activity".
        explicit_full_summary = any(
            term in query_lower
            for term in ("summary", "summarize", "overview", "comprehensive", "most frequent", "top contacts")
        )
        if is_direction_query and not explicit_full_summary:
            is_general_summary_query = False

        dates = [
            date.fromisoformat(value)
            for value in date_values
        ]

        is_period_statistics_query = (
            not is_call_list_query
            and len(dates) >= 2
            and any(
                word in query_lower
                for word in (
                    "statistics",
                    "compare",
                    "comparison",
                    "communication activity",
                    "total interactions",
                    "total duration",
                    "incoming",
                    "outgoing",
                    "communication",
                    "interactions",
                    "calls",
                )
            )
        )

        # The request for a comparison should produce a short conclusion and
        # direction breakdown, not a generic summary with a long contact table.
        if is_period_statistics_query and (comparison_intent or is_direction_query):
            is_general_summary_query = False

        # ---------------------------------------------------------
        # Route 1: Date-range statistics
        # ---------------------------------------------------------

        if is_period_statistics_query:
            start_date, end_date = dates[0], dates[1]

            if end_date < start_date:
                raise ValueError("The end date must not precede the start date.")

            period_records = [
                record for record in records
                if (
                    (dt := _as_datetime(_get(record, "datetime"))) is not None
                    and start_date <= dt.date() <= end_date
                )
            ]

            direction_stats = analyze_communication_direction(
                period_records, number
            )

            print("Target number:", repr(number))
            print("Date range:", start_date, "to", end_date)
            print("Records in period:", len(period_records))
            print("Direction statistics:", direction_stats)

            analysis_type = "period_statistics"
            analysis_data = analyze_period_statistics(
                period_records,
                number,
                start_date,
                end_date,
            )

        elif is_call_list_query:
            selected_directions = set()
            if has_incoming_term:
                selected_directions.add("incoming")
            if has_outgoing_term:
                selected_directions.add("outgoing")

            call_records = records
            if len(dates) >= 2:
                start_date, end_date = dates[0], dates[1]
                if end_date < start_date:
                    raise ValueError("The end date must not precede the start date.")
                call_records = [
                    record for record in call_records
                    if (dt := _as_datetime(_get(record, "datetime"))) is not None
                    and start_date <= dt.date() <= end_date
                ]

            communications = [
                item for item in generate_communication_timeline(call_records, number)
                if item.get("direction") in selected_directions
            ]
            limit = 100
            shown = communications[:limit]
            direction_title = " and ".join(
                label for enabled, label in (
                    (has_incoming_term, "Incoming"),
                    (has_outgoing_term, "Outgoing"),
                ) if enabled
            )
            lines = [f"## {direction_title} calls for {number}"]
            if len(dates) >= 2:
                lines.append(f"**Date range:** {dates[0]} to {dates[1]}")
            if not shown:
                lines.append("No matching call records were found.")
            else:
                lines.extend([
                    "",
                    "| Date and time | Direction | Contact number | Service | Duration (seconds) |",
                    "|---|---|---|---|---:|",
                ])
                lines.extend(
                    f"| {_as_datetime(item['datetime']).strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"{item['direction'].title()} | {item.get('contact_number') or 'Unknown'} | "
                    f"{item.get('service') or 'Unknown'} | {item.get('duration_seconds', 0):,} |"
                    for item in shown
                )
                if len(communications) > limit:
                    lines.extend(["", f"Showing the first {limit} of {len(communications):,} matching records. Add a date range to narrow the list."])
            return self._response(
                "\n".join(lines),
                [self._source(number, "communication_records")],
            )

        # ---------------------------------------------------------
        # Route 2: All six irregular communication patterns
        # ---------------------------------------------------------

        elif is_irregular_query:
            analysis_type = (
                requested_pattern_type.lower()
                if requested_pattern_type and not is_all_patterns_query
                else "irregular_patterns"
            )

            detected_patterns = detect_irregular_patterns(records, number)
            
            # Filter to the requested pattern unless the user asks for all.
            if requested_pattern_type and not is_all_patterns_query:
                detected_patterns = [
                    pattern
                    for pattern in detected_patterns
                    if pattern.get("pattern_type") == requested_pattern_type
                ]

            grouped_patterns = {}
            pattern_counts = {}

            for pattern in detected_patterns:
                pattern_type = pattern.get("pattern_type", "UNKNOWN")
                grouped_patterns.setdefault(pattern_type, []).append(pattern)
                pattern_counts[pattern_type] = (
                    pattern_counts.get(pattern_type, 0) + 1
                )

            analysis_data = {
                "total_patterns": len(detected_patterns),
                "pattern_counts": pattern_counts,
                "patterns": {
                    key: values[:5]
                    for key, values in grouped_patterns.items()
                },
            }

            if not detected_patterns:
                if requested_pattern_type and not is_all_patterns_query:
                    pattern_label = requested_pattern_type.replace("_", " ").title()
                    answer = (
                        f"No {pattern_label.lower()} were detected for {number} "
                        "in the available CDR records."
                    )
                else:
                    answer = (
                        f"No irregular communication patterns were detected "
                        f"for {number} in the available CDR records."
                )
                    
                return self._response(
                    answer,
                    [self._source(number, analysis_type)],
                )

            labels = {
                "HIGH_FREQUENCY": "High-Frequency Contacts",
                "COMMUNICATION_SPIKE": "Communication Spikes",
                "ONE_SIDED_OUTGOING": "Predominantly Outgoing Calls",
                "ONE_SIDED_INCOMING": "Predominantly Incoming Calls",
                "REPEATED_SHORT_CALLS": "Repeated Short Calls",
                "UNUSUAL_COMMUNICATION_HOURS": "Unusual Communication Hours",
            }

            lines = [
                f"## Communication Pattern Analysis: {number}",
                "",
                f"**Potential findings:** {len(detected_patterns)}",
                "",
                "These patterns are indicators for review, not proof of wrongdoing.",
            ]

            for pattern_type, patterns in grouped_patterns.items():
                lines.extend([
                    "",
                    f"### {labels.get(pattern_type, pattern_type.replace('_', ' ').title())} "
                    f"({len(patterns)})",
                ])

                for pattern in patterns[:5]:
                    contact = pattern.get("contact_number", "Unknown")
                    evidence = pattern.get("evidence", {})

                    if pattern_type == "HIGH_FREQUENCY":
                        details = (
                            f"{evidence.get('total_interactions', 0)} interactions; "
                            f"contact average: "
                            f"{evidence.get('average_contact_interactions', 0)}."
                        )
                    elif pattern_type == "COMMUNICATION_SPIKE":
                        details = (
                            f"{evidence.get('interactions_on_date', 0)} interactions on "
                            f"{evidence.get('date', 'an unspecified date')}; "
                            f"{evidence.get('spike_ratio', 0)} times the daily average."
                        )
                    elif pattern_type == "ONE_SIDED_OUTGOING":
                        details = (
                            f"{evidence.get('outgoing_interactions', 0)} outgoing and "
                            f"{evidence.get('incoming_interactions', 0)} incoming; "
                            f"{evidence.get('outgoing_ratio', 0) * 100:.0f}% outgoing."
                        )
                    elif pattern_type == "ONE_SIDED_INCOMING":
                        details = (
                            f"{evidence.get('incoming_interactions', 0)} incoming and "
                            f"{evidence.get('outgoing_interactions', 0)} outgoing; "
                            f"{evidence.get('incoming_ratio', 0) * 100:.0f}% incoming."
                        )
                    elif pattern_type == "REPEATED_SHORT_CALLS":
                        details = pattern.get(
                            "description",
                            f"{evidence.get('short_call_interactions', evidence.get('short_calls', 'Some'))} "
                            "short calls were identified.",
                        )
                    elif pattern_type == "UNUSUAL_COMMUNICATION_HOURS":
                        details = (
                            f"{evidence.get('unusual_hour_interactions', 0)} of "
                            f"{evidence.get('total_interactions', 0)} interactions occurred "
                            f"during {evidence.get('unusual_hours', 'unusual hours')}; "
                            f"{evidence.get('unusual_hour_ratio', 0) * 100:.0f}% of interactions."
                        )
                    else:
                        details = pattern.get(
                            "description",
                            "Potential irregularity detected.",
                        )

                    lines.append(f"- **Contact:** {contact}\n  **Finding:** {details}")

                if len(patterns) > 5:
                    lines.append(
                        f"- {len(patterns) - 5} additional finding(s) in this "
                        "category are not displayed."
                    )

            lines.extend([
                "",
                "Verify the underlying records and case context before drawing conclusions.",
            ])

            return self._response(
                "\n".join(lines),
                [self._source(number, analysis_type)],
            )

        # ---------------------------------------------------------
        # Route 3: Communication network
        # ---------------------------------------------------------

        elif is_network_query:
            analysis_type = "communication_network"
            network = generate_communication_network(records, number)

            nodes = network.get("nodes", [])
            edges = network.get("edges", [])

            sorted_edges = sorted(
                edges,
                key=lambda edge: edge.get("total_interactions", 0),
                reverse=True,
            )
            top_edges = sorted_edges[:10]

            # Support either source/target or from/to edge conventions.
            visible_contact_ids = set()
            for edge in top_edges:
                for endpoint_key in ("source", "target", "from", "to"):
                    endpoint = edge.get(endpoint_key)
                    if endpoint is not None and str(endpoint) != str(number):
                        visible_contact_ids.add(str(endpoint))

            visible_nodes = [
                node for node in nodes
                if str(node.get("id")) == str(number)
                or str(node.get("id")) in visible_contact_ids
            ]

            analysis_data = {
                "total_nodes": len(nodes),
                "total_contacts": len(edges),
                "total_interactions": sum(
                    edge.get("total_interactions", 0) for edge in edges
                ),
                "top_contacts": top_edges,
                "nodes": visible_nodes,
                "edges": top_edges,
            }

            answer_lines = [
                f"## Communication Network: {number}",
                "",
                f"- **Contacts:** {len(edges)}",
                f"- **Total interactions:** {analysis_data['total_interactions']:,}",
                "",
                "The graph shows the most frequent connections and their "
                "communication activity. Select a connection in the graph "
                "to inspect its details.",
            ]

            return self._response(
                "\n".join(answer_lines),
                [self._source(number, "communication_network")],
                visualization={
                    "type": "communication_network",
                    "data": {
                        "nodes": analysis_data["nodes"],
                        "edges": analysis_data["edges"],
                    },
                },
            )

        # ---------------------------------------------------------
        # Route 4: Communication timeline
        # ---------------------------------------------------------

        elif is_timeline_query:
            analysis_type = "communication_timeline"
            timeline = generate_communication_timeline(records, number)

            # Normalize and sort timestamps before summarizing.
            valid_timeline = []
            for item in timeline:
                item_dt = _as_datetime(item.get("datetime"))
                if item_dt is not None:
                    normalized = dict(item)
                    normalized["datetime"] = item_dt
                    valid_timeline.append(normalized)

            valid_timeline.sort(key=lambda item: item["datetime"])

            if valid_timeline:
                daily_activity = {}

                for item in valid_timeline:
                    date_key = item["datetime"].date().isoformat()
                    daily_activity.setdefault(
                        date_key,
                        {
                            "total_interactions": 0,
                            "incoming_interactions": 0,
                            "outgoing_interactions": 0,
                        },
                    )

                    daily_activity[date_key]["total_interactions"] += 1
                    if item.get("direction") == "incoming":
                        daily_activity[date_key]["incoming_interactions"] += 1
                    else:
                        daily_activity[date_key]["outgoing_interactions"] += 1

                busiest_dates = sorted(
                    [
                        {"date": day, **activity}
                        for day, activity in daily_activity.items()
                    ],
                    key=lambda item: item["total_interactions"],
                    reverse=True,
                )[:10]

                analysis_data = {
                    "total_interactions": len(valid_timeline),
                    "timeline_start": valid_timeline[0]["datetime"].isoformat(),
                    "timeline_end": valid_timeline[-1]["datetime"].isoformat(),
                    "first_5_communications": valid_timeline[:5],
                    "last_5_communications": valid_timeline[-5:],
                    "busiest_communication_dates": busiest_dates,
                    "total_active_days": len(daily_activity),
                }
            else:
                analysis_data = {
                    "total_interactions": 0,
                    "timeline_start": None,
                    "timeline_end": None,
                    "first_5_communications": [],
                    "last_5_communications": [],
                    "busiest_communication_dates": [],
                    "total_active_days": 0,
                }

        # ---------------------------------------------------------
        # Route 5: Interactions by contact
        # ---------------------------------------------------------

        elif is_interactions_query:
            analysis_type = "contact_interactions"
            interaction_data = analyze_interactions(records, number)

            if isinstance(interaction_data, dict):
                interactions = interaction_data.get(
                    "interactions",
                    interaction_data.get("contacts", []),
                )
                if not interactions and any(
                    key in interaction_data
                    for key in (
                        "contact_number",
                        "total_interactions",
                        "incoming_interactions",
                    )
                ):
                    interactions = [interaction_data]
            elif isinstance(interaction_data, list):
                interactions = interaction_data
            else:
                interactions = []

            if not interactions:
                return self._response(
                    f"No interactions were found for {number}.",
                    [self._source(number, analysis_type)],
                )

            interactions = sorted(
                interactions,
                key=lambda item: (
                    item.get("total_interactions", 0)
                    if isinstance(item, dict)
                    else 0
                ),
                reverse=True,
            )

            shown = interactions[:10]
            lines = [
                f"## Contact interactions for {number}",
                f"**Unique contacts found:** {len(interactions)}",
            ]

            for index, item in enumerate(shown, 1):
                if not isinstance(item, dict):
                    continue

                contact = (
                    item.get("contact_number")
                    or item.get("called_number")
                    or item.get("contact")
                    or "Unknown"
                )

                lines.extend([
                    "",
                    f"### {index}. {contact}",
                    f"- Total interactions: {item.get('total_interactions', 0)}",
                    f"- Incoming: {item.get('incoming_interactions', 0)}",
                    f"- Outgoing: {item.get('outgoing_interactions', 0)}",
                    f"- Total duration: {_format_duration(item.get('total_duration_seconds', 0))}",
                    f"- Last communication: {item.get('last_communication') or 'N/A'}",
                ])

            if len(interactions) > 10:
                lines.append(
                    f"\nShowing 10 of {len(interactions)} contacts."
                )

            return self._response(
                "\n".join(lines),
                [self._source(number, analysis_type)],
            )

        # ---------------------------------------------------------
        # Route 6: Comprehensive summary
        # This must precede frequency/direction-only routing.
        # ---------------------------------------------------------

        elif is_general_summary_query:
            direction = analyze_communication_direction(records, number)
            frequency = analyze_communication_frequency(records, number)

            analysis_type = "general_summary"
            analysis_data = {
                "total_interactions": direction.get("total_interactions", 0),
                "incoming": direction.get("incoming", {}),
                "outgoing": direction.get("outgoing", {}),
                "total_duration_seconds": direction.get(
                    "total_duration_seconds", 0
                ),
                "total_unique_contacts": len(frequency),
                "most_frequent_contacts": frequency[:10],
            }

        # ---------------------------------------------------------
        # Route 7: Communication frequency
        # ---------------------------------------------------------

        elif is_frequency_query:
            frequency = analyze_communication_frequency(records, number)
            analysis_type = "communication_frequency"
            analysis_data = {
                "total_unique_contacts": len(frequency),
                "most_frequent_contacts": frequency[:10],
            }

        # ---------------------------------------------------------
        # Route 8: Incoming/outgoing direction
        # ---------------------------------------------------------

        elif is_direction_query:
            analysis_type = "communication_direction"
            analysis_data = analyze_communication_direction(records, number)

        # ---------------------------------------------------------
        # Default: comprehensive CDR summary
        # ---------------------------------------------------------

        else:
            direction = analyze_communication_direction(records, number)
            frequency = analyze_communication_frequency(records, number)

            analysis_type = "general_summary"
            analysis_data = {
                "total_interactions": direction.get("total_interactions", 0),
                "incoming": direction.get("incoming", {}),
                "outgoing": direction.get("outgoing", {}),
                "total_duration_seconds": direction.get(
                    "total_duration_seconds", 0
                ),
                "total_unique_contacts": len(frequency),
                "most_frequent_contacts": frequency[:10],
            }

        # These values are already computed from CDR records. A document-quote
        # validator must not decide whether numeric API statistics are answerable.
        stats = analysis_data.get("statistics", analysis_data)
        lines = [f"## Communication activity for {number}"]
        # General activity questions read better as a narrative with ranked
        # contacts. Focused questions below keep their compact data formats.
        if analysis_type == "general_summary":
            incoming_count = stats.get("incoming", {}).get("count", 0)
            outgoing_count = stats.get("outgoing", {}).get("count", 0)
            total = stats.get("total_interactions", incoming_count + outgoing_count)
            total_duration = stats.get("total_duration_seconds", 0)
            lines = [
                f"The communication activity for the target number {number} involves a total of "
                f"{outgoing_count:,} outgoing interactions and {incoming_count:,} incoming interactions "
                f"({total:,} interactions overall)."
            ]
            contacts = analysis_data.get("most_frequent_contacts", [])
            if contacts:
                lines.extend(["", "The 10 most frequent contacts are:"])
                for index, item in enumerate(contacts[:10], 1):
                    contact_number = item.get("contact_number", "Unknown")
                    name = item.get("contact_name")
                    label = f"{name} ({contact_number})" if name and name.lower() != "unknown" else contact_number
                    average = item.get("average_duration_seconds")
                    average_text = f"{float(average):.2f}" if average is not None else "unavailable"
                    lines.append(
                        f"{index}. Contact Number: {label} - Total Interactions: "
                        f"{item.get('total_interactions', 0):,} - Average Duration: {average_text} seconds"
                    )
            else:
                lines.extend(["", "No contact records were found."])
            lines.extend([
                "",
                f"The total duration of all interactions is {total_duration:,} seconds ({_format_duration(total_duration)}).",
                f"There are {analysis_data.get('total_unique_contacts', 0):,} unique contacts.",
                "These figures describe recorded activity and do not by themselves establish irregularity or misconduct.",
            ])
            return self._response("\n".join(lines), [self._source(number, analysis_type)])

        if analysis_type == "period_statistics":
            lines = [
                f"## Incoming vs. outgoing communication for {number}",
                f"**Date range:** {analysis_data['start_date']} to {analysis_data['end_date']}",
            ]
        if analysis_type == "communication_timeline":
            lines = [f"## Communication timeline for {number}"]
            total = analysis_data.get("total_interactions", 0)
            lines.extend([
                f"**Total interactions:** {total:,}",
                f"**Active days:** {analysis_data.get('total_active_days', 0):,}",
            ])
            start = analysis_data.get("timeline_start")
            end = analysis_data.get("timeline_end")
            if start and end:
                start_dt = _as_datetime(start)
                end_dt = _as_datetime(end)
                start_display = start_dt.strftime("%b %d, %Y at %H:%M") if start_dt else start
                end_display = end_dt.strftime("%b %d, %Y at %H:%M") if end_dt else end
                lines.append(f"**Date range:** {start_display} to {end_display}")
            else:
                lines.append("No communication records matched this number.")

            first = analysis_data.get("first_5_communications", [])
            last = analysis_data.get("last_5_communications", [])
            if first:
                lines.extend(["", "**First communications**", "", "| Date and time | Direction | Contact | Service | Duration (seconds) |", "|---|---|---|---|---:|"])
                lines.extend(
                    f"| {item['datetime'].isoformat()} | {item.get('direction', 'unknown').title()} | "
                    f"{item.get('contact_name') or 'Unknown'} ({item.get('contact_number') or 'Unknown'}) | "
                    f"{item.get('service') or 'Unknown'} | {item.get('duration_seconds', 0):,} |"
                    for item in first
                )
            if last and total > len(first):
                lines.extend(["", "**Most recent communications**", "", "| Date and time | Direction | Contact | Service | Duration (seconds) |", "|---|---|---|---|---:|"])
                lines.extend(
                    f"| {item['datetime'].isoformat()} | {item.get('direction', 'unknown').title()} | "
                    f"{item.get('contact_name') or 'Unknown'} ({item.get('contact_number') or 'Unknown'}) | "
                    f"{item.get('service') or 'Unknown'} | {item.get('duration_seconds', 0):,} |"
                    for item in last
                )
        if analysis_type == "communication_frequency":
            contacts = analysis_data.get("most_frequent_contacts", [])
            count = analysis_data.get("total_unique_contacts", 0)
            lines = [f"The most frequent contacts for target number {number} ({count:,} unique contacts) are:"]
            if contacts:
                for index, item in enumerate(contacts, 1):
                    average = item.get("average_duration_seconds")
                    average_text = f"{float(average):.2f}" if average is not None else "unavailable"
                    lines.append(
                        f"{index}. Contact Number: {item.get('contact_number', 'Unknown')} - "
                        f"Total Interactions: {item.get('total_interactions', 0):,} - "
                        f"Average Duration: {average_text} seconds"
                    )
            else:
                lines.append("No contact records were found.")
            return self._response("\n".join(lines), [self._source(number, analysis_type)])

        if "incoming" in stats and "outgoing" in stats:
            incoming_count = stats["incoming"].get("count", 0)
            outgoing_count = stats["outgoing"].get("count", 0)
            if analysis_type == "period_statistics":
                difference = abs(incoming_count - outgoing_count)
                if incoming_count == outgoing_count:
                    conclusion = "Incoming and outgoing communication had the same number of interactions."
                else:
                    higher = "Incoming" if incoming_count > outgoing_count else "Outgoing"
                    conclusion = f"{higher} communication had {difference:,} more interactions in this period."
                lines.extend([
                    "",
                    f"There were {incoming_count:,} incoming and {outgoing_count:,} outgoing interactions "
                    f"({stats.get('total_interactions', incoming_count + outgoing_count):,} total).",
                    conclusion,
                    f"Total recorded duration was {stats.get('total_duration_seconds', 0):,} seconds "
                    f"({_format_duration(stats.get('total_duration_seconds', 0))}).",
                ])
                return self._response("\n".join(lines), [self._source(number, analysis_type)])
            lines.extend([
                f"**Total interactions:** {stats.get('total_interactions', incoming_count + outgoing_count):,}",
                "", "| Direction | Interactions | Duration (seconds) |", "|---|---:|---:|",
                f"| Incoming | {incoming_count:,} | {stats['incoming'].get('duration_seconds', 0):,} |",
                f"| Outgoing | {outgoing_count:,} | {stats['outgoing'].get('duration_seconds', 0):,} |", "",
            ])
            if incoming_count == outgoing_count:
                lines.append("Incoming and outgoing had the same number of interactions.")
            else:
                higher = "Incoming" if incoming_count > outgoing_count else "Outgoing"
                lines.append(f"{higher} had {abs(incoming_count - outgoing_count):,} more interactions.")
            if not incoming_count and not outgoing_count:
                lines.append("No communication records matched the requested scope.")
        contacts = analysis_data.get("most_frequent_contacts", analysis_data.get("contacts", []))
        contact_count = analysis_data.get("total_unique_contacts", analysis_data.get("total_contacts"))
        if contact_count is not None:
            lines.append(f"\n**Unique contacts:** {contact_count:,}")
        if contacts:
            lines.extend(["", "**Most frequent contacts**", "", "| Contact | Interactions |", "|---|---:|"])
            lines.extend(f"| {item.get('contact_number', 'Unknown')} | {item.get('total_interactions', 0):,} |"
                         for item in sorted(contacts, key=lambda item: item.get('total_interactions', 0), reverse=True)[:10])
        answer = "\n".join(lines)

        response_data = {
            "answer": answer,
            "sources": [self._source(number, analysis_type)],
        }

        if analysis_type == "communication_network":
            response_data["visualization"] = {
                "type": "communication_network",
                "data": {
                    "nodes": analysis_data["nodes"],
                    "edges": analysis_data["edges"],
                },
            }

        return {"success": True, "response": response_data}

    @staticmethod
    def _get_context_identifiers(context: dict) -> dict:
        """Extract the most recent phone number and CID from conversation history."""
        identifiers = {
            "phone_number": None,
            "cid": None,
        }

        messages = context.get("messages", [])

        # Search newest messages first.
        for message in reversed(messages):
            content = str(message.get("content", ""))

            if identifiers["phone_number"] is None:
                phone_match = re.search(
                    r"(?<!\d)[0-9]{8}(?!\d)",
                    content,
                )
                if phone_match:
                    identifiers["phone_number"] = phone_match.group(0)

            if identifiers["cid"] is None:
                cid_match = re.search(
                    r"(?<!\d)[0-9]{11}(?!\d)",
                    content,
                )
                if cid_match:
                    identifiers["cid"] = cid_match.group(0)

            if identifiers["phone_number"] and identifiers["cid"]:
                break

        return identifiers

    @staticmethod
    def _get_document_context(context: dict) -> str | None:
        """
        Build document context from recent user messages,
        excluding the current question.
        """
        messages = context.get("messages", [])
        current_query = context.get("current_query", "").strip()

        previous_user_messages = []

        for message in messages:
            if message.get("role") != "user":
                continue

            content = str(message.get("content", "")).strip()

            if not content:
                continue

            # Current message was already saved before context was loaded.
            if current_query and content == current_query:
                continue

            previous_user_messages.append(content)

        # Keep only the most recent 4 previous user messages.
        previous_user_messages = previous_user_messages[-4:]

        if not previous_user_messages:
            return None

        return "\n".join(previous_user_messages)

    
    # =============================================================
    # Main query router
    # =============================================================

    async def query(self, query: str, context: dict | None = None) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")

        query = query.strip()
        query_lower = query.lower()
        context = context or {}

        context_identifiers = self._get_context_identifiers(context)

        context_phone = context_identifiers.get("phone_number")
        context_cid = context_identifiers.get("cid")

        # A case timeline is a document request even when the question does not
        # repeat "statement" or "case" (for example, "timeline for Haa case").
        case_match = (
            re.search(r"\b(?:case\s*(?:no\.?|number)?\s*)([A-Za-z0-9][A-Za-z0-9/-]{1,30})\b", query, re.I)
            or re.search(r"\b([A-Za-z0-9][A-Za-z0-9/-]{1,30})\s+case\b", query, re.I)
        )
        explicit_case_ref = bool(re.search(r"\bcase\b", query, re.I))
        has_timeline_term = any(term in query_lower for term in ("timeline", "chronology", "sequence of events"))
        is_document_timeline_query = has_timeline_term and explicit_case_ref and not re.search(r"(?<!\d)[0-9]{8}(?!\d)", query)

        previous_document_context = self._get_document_context(context)

        # ---------------------------------------------------------
        # Cross-system evidence comparison
        # Must run before the individual relationship/CDR routes.
        # ---------------------------------------------------------

        requested_systems = self._requested_evidence_systems(query_lower)
        print("QUERY RECEIVED:", repr(query))
        print("REQUESTED SYSTEMS:", requested_systems)

        if len(requested_systems) >= 2 and not is_document_timeline_query:
            print("ROUTE: COMBINED EVIDENCE")
            return await self._handle_combined_query(query)

        if is_document_timeline_query:
            try:
                case_no = case_match.group(1) if case_match else None
                timeline = self.statement_service.build_timeline(case_no=case_no)
                if timeline:
                    lines = ["## Chronological Case Timeline", ""]
                    for event in timeline:
                        event_date = event.get("date") or "(no date)"
                        event_time = f" ({event.get('time')})" if event.get("time") else ""
                        source = event.get("source") or {}
                        citation = f" [{source['sentence_id']}]" if source.get("sentence_id") else ""
                        lines.append(f"- **{event_date}{event_time}:** {event.get('event', 'Unspecified event')}{citation}")
                    return self._response("\n".join(lines), [{"type": "Statement Timeline", "events_count": len(timeline), "case_no": case_no}])
                return self._response(
                    f"No document timeline events were found{f' for case {case_no}' if case_no else ''}.",
                    [{"type": "Statement Timeline", "events_count": 0, "case_no": case_no}],
                )
            except Exception as exc:
                print(f"Statement timeline error: {exc}")

        # Relationship API routing: CID is exactly 11 digits.
        cid_match = re.search(r"(?<!\d)[0-9]{11}(?!\d)", query)

        relationship_keywords = (
            "relationship",
            "relationships",
            "family",
            "family tree",
            "relatives",
            "parent",
            "parents",
            "siblings",
            "sibling",
            "spouse",
            "children",
            "degree",
        )

        is_relationship_query = any(
            word in query_lower for word in relationship_keywords
        )

        if is_relationship_query:
            resolved_cid = (
                cid_match.group(0)
                if cid_match
                else context_cid
            )

            if resolved_cid:
                return await self._handle_relationship_query(
                    query,
                    query_lower,
                    resolved_cid,
                )

        # CDR routing uses exactly 8 ASCII digits, not arbitrary numeric IDs.
        cdr_keywords = (
            "cdr",
            "call",
            "calls",
            "communication",
            "communications",
            "contact",
            "contacts",
            "interaction",
            "interactions",
            "incoming",
            "outgoing",
            "duration",
            "irregular",
            "suspicious",
            "unusual",
            "anomal",
            "frequency",
            "frequent",
            "timeline",
            "network",
            "history",
        )

        is_cdr_query = any(
            word in query_lower for word in cdr_keywords
        )

        number_matches = re.findall(
            r"(?<!\d)[0-9]{8}(?!\d)",
            query,
        )

        if is_cdr_query:
            target_match = re.search(r"\btarget(?:\s+number)?\s*[:=]?\s*([0-9]{8})(?!\d)", query, re.I)
            resolved_number = (
                target_match.group(1) if target_match else number_matches[0]
                if number_matches
                else context_phone
            )

            if resolved_number:
                return await self._handle_cdr_query(
                    query,
                    query_lower,
                    resolved_number,
                )

        if is_cdr_query and not number_matches:
            # Do not silently send an incomplete CDR request to document RAG.
            if re.search(r"(?<!\d)[0-9]{5,20}(?!\d)", query):
                answer = (
                    "I couldn't identify a valid 8-digit target phone number "
                    "in your request. Please provide the number and try again."
                )
            else:
                answer = (
                    "Please provide the target's 8-digit phone number so I "
                    "can retrieve the relevant CDR information."
                )

            return self._response(answer)

        # ---------------------------------------------------------
        # Statement contradiction detection
        # ---------------------------------------------------------

        contradiction_keywords = (
            "contradiction",
            "contradictions",
            "conflicting statement",
            "conflicting statements",
            "discrepancy",
            "discrepancies",
        )

        is_contradiction_query = (
            any(word in query_lower for word in contradiction_keywords)
            and any(
                word in query_lower
                for word in ("statement", "witness", "accused")
            )
        )

        if is_contradiction_query:
            try:
                contradiction_data = await run_in_threadpool(self.statement_service.detect_contradictions)
                if contradiction_data.get("success") is False:
                    raise RuntimeError(contradiction_data.get("error", "Contradiction analysis failed."))
                if "contradictions" in contradiction_data:
                    analyzed = contradiction_data.get("analyzed_statements", [])
                    if not analyzed:
                        return self._response("No statement documents are available for comparison.")
                    findings = contradiction_data["contradictions"]
                    lines = ["## Statement comparison", ""]
                    sources = {}
                    if findings:
                        lines.append("Potential contradictions for investigator review:")
                        for index, finding in enumerate(findings, 1):
                            lines.append(f"\n**{index}.** {finding.get('explanation', '')}")
                            for side in ("a", "b"):
                                claim = finding[side]
                                sid = claim["sentence_id"]
                                lines.append(f"- {claim.get('person', 'Witness')}: {claim['quote']} [{sid}]")
                                doc_id = claim["doc_id"]
                                source = sources.setdefault(doc_id, {
                                    "doc_id": doc_id, "filename": f"{doc_id}.txt",
                                    "person_name": claim.get("person", ""),
                                    "sentence_ids": [], "excerpt": "",
                                })
                                if sid not in source["sentence_ids"]:
                                    source["sentence_ids"].append(sid)
                                    source["excerpt"] += f"[{sid}] {claim['quote']}\n"
                    elif contradiction_data.get("warnings"):
                        lines.append("The comparison is incomplete. No contradiction finding can be given for the pairs that could not be evaluated.")
                    else:
                        lines.append("No explicit factual contradictions were identified in the compared claims. This does not establish that every statement is consistent.")
                    if "pairs_judged" in contradiction_data:
                        lines.append(f"\nReviewed {contradiction_data['pairs_judged']} of {contradiction_data.get('pairs_selected', 0)} selected sentence pairs; this is not an exhaustive comparison.")
                    lines.append(f"\nAnalyzed {len(analyzed)} statement document(s). Verify findings against the original statements.")
                    return self._response("\n".join(lines), list(sources.values()))
                result = contradiction_data["result"]
                findings = result.get("findings", [])
                overall = result.get(
                    "overall_result",
                    "NO CONTRADICTION FOUND",
                )

                lines = [
                    f"## Statement Contradiction Analysis: {overall}",
                    "",
                ]

                if findings:
                    lines.append(
                        f"Identified {len(findings)} factual contradiction(s) "
                        "across the analyzed statements."
                    )

                    for index, finding in enumerate(findings, 1):
                        lines.append(
                            f"\n**{index}. Subject: "
                            f"{finding.get('subject', 'Unknown').title()} "
                            f"({finding.get('type', 'Attribute').title()})**"
                        )
                        for value in finding.get("values", []):
                            sources = ", ".join(value.get("statements", []))
                            lines.append(
                                f"- Claim: \"{value.get('value')}\" "
                                f"(Source: {sources})"
                            )
                else:
                    lines.append(
                        "No explicit factual contradictions were found "
                        "across the analyzed statement claims."
                    )

                return self._response(
                    "\n".join(lines),
                    [{
                        "type": "Statement Contradiction Analysis",
                        "statements": contradiction_data.get(
                            "analyzed_statements", []
                        ),
                    }],
                )
            except Exception as exc:
                print(f"Statement contradiction analysis error: {exc}")
                raise RuntimeError("Statement comparison could not be completed. Please retry; no conclusion about contradictions was reached.") from exc

        # ---------------------------------------------------------
        # List available statements
        # ---------------------------------------------------------

        list_phrases = (
            "list statements",
            "list the statements",
            "list all statements",
            "list all the statements",
            "show statements",
            "show all statements",
            "available statements",
            "what statements do we have",
            "what statements are available",
            "witness statements available",
            "all witness statements",
        )

        is_list_statements = (
            any(phrase in query_lower for phrase in list_phrases)
            and not any(
                word in query_lower
                for word in ("contradiction", "summarize", "summary")
            )
        )

        if is_list_statements:
            try:
                statements = self.statement_service.list_statements()

                if statements:
                    lines = [
                        f"Found {len(statements)} statement document(s):",
                        "",
                    ]

                    for index, statement in enumerate(statements, 1):
                        lines.append(
                            f"{index}. **{statement.get('name', 'Unknown')}** "
                            f"(Document ID: `{statement.get('statement_id', 'N/A')}`)\n"
                            f"   - CID: {statement.get('cid', 'N/A')}\n"
                            f"   - Occupation: {statement.get('occupation', 'N/A')}\n"
                            f"   - Dzongkhag: {statement.get('dzongkhang', 'N/A')}\n"
                            f"   - Phone: {statement.get('phone_number', 'N/A')}"
                        )

                    return self._response(
                        "\n".join(lines),
                        [
                            {
                                "type": "Statement Documents",
                                "statement_id": statement.get("statement_id"),
                                "name": statement.get("name"),
                            }
                            for statement in statements
                        ],
                    )

                return self._response("No statement documents were found.")

            except Exception as exc:
                print(f"List statements error: {exc}")

        # ---------------------------------------------------------
        # Statement summarization
        # ---------------------------------------------------------

        is_statement_summary_query = (
            any(
                word in query_lower
                for word in (
                    "summarize",
                    "summary",
                    "brief overview",
                    "key points",
                )
            )
            and (
                "statement" in query_lower
                or any(
                    name in query_lower
                    for name in ("kinga", "prem", "tashi")
                )
            )
        )

        if is_statement_summary_query:
            try:
                statements = self.statement_service.list_statements()
                target_statement = None

                statement_match = re.search(
                    r"statement\s*[_#]?\s*(\d+)",
                    query_lower,
                )

                if statement_match:
                    statement_id = f"statement_{statement_match.group(1)}"
                    target_statement = next(
                        (
                            statement for statement in statements
                            if statement.get("statement_id") == statement_id
                        ),
                        None,
                    )

                if target_statement is None:
                    for statement in statements:
                        name = statement.get("name", "")
                        if name and name.lower() in query_lower:
                            target_statement = statement
                            break

                # Preserve the previous default behaviour when no statement
                # is specified, though asking for a statement ID is clearer.
                if target_statement is None and statements:
                    target_statement = statements[0]

                if target_statement:
                    result = self.statement_service.summarize_statement(
                        target_statement["statement_id"]
                    )

                    if result.get("success"):
                        lines = [
                            f"## Summary of Statement: "
                            f"{target_statement.get('name', 'Unknown')} "
                            f"({target_statement['statement_id']})",
                            "",
                            result.get("summary", ""),
                        ]

                        key_points = result.get("key_points", [])
                        if key_points:
                            lines.extend(["", "**Key Points:**"])
                            for point in key_points:
                                citations = " ".join(
                                    f"[{citation}]"
                                    for citation in point.get("sentence_ids", [])
                                )
                                lines.append(
                                    f"- {point.get('point', '')} {citations}".strip()
                                )

                        return self._response(
                            "\n".join(lines),
                            [{
                                "type": "Statement Summary",
                                "statement_id": target_statement["statement_id"],
                                "name": target_statement.get("name"),
                            }],
                        )

            except Exception as exc:
                print(f"Statement summarization error: {exc}")

        # ---------------------------------------------------------
        # Statement chronology / timeline
        # ---------------------------------------------------------

        is_statement_timeline_query = (
            any(
                word in query_lower
                for word in ("timeline", "chronology", "sequence of events")
            )
            and any(
                word in query_lower
                for word in ("statement", "witness", "case")
            )
        )

        if is_statement_timeline_query:
            try:
                timeline = self.statement_service.build_timeline(
                    case_no=case_match.group(1) if case_match else None
                )

                if timeline:
                    lines = ["## Chronological Case Timeline", ""]

                    for event in timeline:
                        event_date = event.get("date") or "(no date)"
                        event_time = (
                            f" ({event.get('time')})"
                            if event.get("time")
                            else ""
                        )
                        source = event.get("source") or {}
                        sentence_id = source.get("sentence_id")
                        citation = (
                            f" [{sentence_id}]"
                            if sentence_id
                            else ""
                        )

                        lines.append(
                            f"- **{event_date}{event_time}:** "
                            f"{event.get('event', 'Unspecified event')}{citation}"
                        )

                    return self._response(
                        "\n".join(lines),
                        [{
                            "type": "Statement Timeline",
                            "events_count": len(timeline),
                        }],
                    )

            except Exception as exc:
                print(f"Statement timeline error: {exc}")

        # ---------------------------------------------------------
        # Statement evidence RAG
        # ---------------------------------------------------------

        known_statement_names = (
            "kinga norbu",
            "prem kr rai",
            "tashi topden",
        )

        is_statement_query = (
            "statement" in query_lower
            or any(name in query_lower for name in known_statement_names)
        )

        if is_statement_query:
            try:
                statement_result = (
                    await run_in_threadpool(
                        self.statement_service.query_statement_evidence, query=query
                    )
                )

                if (
                    statement_result.get("success")
                    and statement_result.get("answer")
                ):
                    return {
                        "success": True,
                        "response": {
                            "answer": statement_result["answer"],
                            "sources": statement_result.get("sources", []),
                            "warnings": statement_result.get("warnings", []),
                            "disclaimer": statement_result.get("disclaimer", ""),
                        },
                    }

            except Exception:
                # Do not start a second model call after a failed document request.
                raise

        # ---------------------------------------------------------
        # Normal investigation-document RAG
        # ---------------------------------------------------------

        rag_query = query

        if previous_document_context:
            rag_query = (
                f"{previous_document_context}\n"
                f"Follow-up question: {query}"
            )

        rag_result = await run_in_threadpool(
            self.rag_service.query,
            rag_query,
            user_query=query,
            )
        

        return {
            "success": True,
            "response": rag_result,
        }

    def close(self):
        for service in (
            self._rag_service,
            self._cdr_service,
            self._llm_service,
        ):
            if service and hasattr(service, "close"):
                service.close()
