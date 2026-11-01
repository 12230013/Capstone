import json


class PromptService:
    # ============================================================
    # RAG / INVESTIGATION DOCUMENTS
    # ============================================================

    def build_prompt(
        self,
        query: str,
        retrieved_chunks: list[dict],
    ) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")

        if not isinstance(retrieved_chunks, list):
            raise ValueError("retrieved_chunks must be a list.")

        evidence_sections = []

        for index, chunk in enumerate(retrieved_chunks, start=1):
            if not isinstance(chunk, dict):
                continue

            text = chunk.get("text", "")
            metadata = chunk.get("metadata", {})

            if not isinstance(metadata, dict):
                metadata = {}

            # Support both flat and nested metadata structures.
            file_metadata = metadata.get("metadata", metadata)

            if not isinstance(file_metadata, dict):
                file_metadata = {}

            filename = (
                file_metadata.get("filename")
                or file_metadata.get("file_name")
                or "Unknown source"
            )

            case_number = (
                file_metadata.get("case_no")
                or file_metadata.get("case_number")
                or file_metadata.get("case_id")
            )

            person_name = (
                file_metadata.get("person_name")
                or file_metadata.get("person")
                or file_metadata.get("name")
            )

            source = f"Source: {filename}"
            if case_number:
                source += f"\nCase: {case_number}"

            if person_name:
                source += f"\nPerson: {person_name}"

            evidence_sections.append(
                f"[Evidence {index}]\n"
                f"{source}\n"
                f"Content: {text}"
            )

        evidence = "\n\n".join(evidence_sections)

        if not evidence:
            evidence = "No usable investigation evidence was retrieved."

        return f"""
You are an AI assistant supporting authorized ACC investigators.

Answer the user's question using only the investigation evidence below.

Rules:
1. Do not use outside knowledge, assumptions, or invented details.
2. Identify the relevant investigation case, person, event, or date.
3. If evidence relates to multiple cases and the user has not
   specified a case, ask which case they mean. Mention the available
   case numbers when they can be identified reliably.
4. If a case is specified, use evidence from that case only, unless
   the user explicitly requests a comparison or a supported link
   between cases is established in the evidence.
5. Do not treat similar events across different cases as the same event.
6. If evidence is insufficient, state what cannot be established.
7. Distinguish documented facts from allegations, statements, and
   unverified claims.
8. Cite the supporting source document for factual findings whenever
   the source is available. Do not invent page numbers or citations.
9. Keep the response concise, structured, and relevant to the question.
10. When multiple evidence chunks describe the same fact, event,
    transaction, or statement, consolidate them into one finding rather
    than repeating the same information.
11. Do not present duplicate or near-duplicate evidence as separate
    findings merely because it appears in multiple retrieved chunks.

Investigation Evidence:
{evidence}

User Question:
{query}

Answer:
""".strip()

    # ============================================================
    # CDR ANALYSIS
    # ============================================================

    def build_cdr_prompt(
        self,
        query: str,
        cdr_data: dict,
    ) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")

        if not isinstance(cdr_data, dict):
            raise ValueError("cdr_data must be a dictionary.")

        target_number = cdr_data.get("target_number")
        if not target_number:
            raise ValueError("cdr_data must contain target_number.")

        analysis_type = cdr_data.get("analysis_type", "general")

        return f"""
You are an AI assistant supporting authorized ACC investigators.

Answer the user's question using only the supplied CDR analysis.

Rules:
1. Treat the supplied analysis as the authoritative source for
   communication statistics.
2. Preserve the exact target_number: {target_number}
3. Never confuse the target number with a contact_number.
4. Do not modify, shorten, or remove digits from any phone number.
5. Use only the counts, dates, times, durations, names, ratios, and
   other values explicitly supplied in the analysis.
6. Do not calculate or invent additional statistics.
7. Preserve the order of ranked lists such as top contacts.
8. For timeline questions, report only timeline information present
   in the analysis. Do not invent timestamps or aggregate records.
9. For network questions, report only supplied network statistics
   and listed contacts. Do not imply that a partial contact list is
   the complete network.
10. For irregular-pattern questions, summarize only the detected
    patterns supplied in the analysis. If a total or pattern count
    is missing, do not invent it.
11. Explain that irregular patterns are indicators for further
    investigation, not proof of wrongdoing.
12. Do not infer that a person committed misconduct from call records.
13. If the analysis cannot answer the question, clearly state that
    the available CDR data is insufficient.
14. Do not generate code or claim to have performed additional analysis.
15. Keep the response concise and focused on the user's question.

Analysis type:
{analysis_type}

Target phone number:
{target_number}

CDR Analysis:
{json.dumps(cdr_data, indent=2, default=str, ensure_ascii=False)}

User Question:
{query}

Answer:
""".strip()

    # ============================================================
    # RELATIONSHIP MAPPING
    # ============================================================

    def build_relationship_prompt(
        self,
        query: str,
        relationship_data: dict,
    ) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")

        if not isinstance(relationship_data, dict):
            raise ValueError("relationship_data must be a dictionary.")

        return f"""
You are an AI assistant supporting authorized ACC investigators.

Answer the user's question using only the supplied Relationship
Mapping API data.

Rules:
1. Treat the API response as the authoritative source for the
   relationships it reports.
2. Identify the target person from the supplied target field.
   Do not confuse the target with their relatives.
3. Describe relationships using the relationship types and fields
   actually provided.
4. Distinguish TARGET and SPOUSE sides when a side field is available.
5. Use relatedTo when available to explain the person to whom a
   relationship is connected.
6. Respect the requested relationship degree. Do not assign a degree
   unless supported by the data.
7. For family-tree questions, summarize the supplied relationships
   without claiming the data contains every possible relative.
8. Do not invent names, citizen IDs, family connections, or
   relationship types.
9. If a field is null, missing, or unavailable, do not guess its value.
10. If the data is insufficient, state that clearly.
11. Family relationships alone are not evidence of corruption,
    criminal activity, or wrongdoing.
12. Keep the answer concise, structured, and relevant to the question.

Relationship Mapping API Data:
{json.dumps(relationship_data, indent=2, default=str, ensure_ascii=False)}

User Question:
{query}

Answer:
""".strip()
