from importlib.metadata import metadata
import json
class PromptService:

    def build_prompt(
        self,
        query: str,
        retrieved_chunks: list[dict]
    ) -> str:

        if not isinstance(query, str):
            raise ValueError("Query must be a string.")

        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if not isinstance(retrieved_chunks, list):
            raise ValueError("retrieved_chunks must be a list.")

        evidence_sections = []

        for index, chunk in enumerate(retrieved_chunks, start=1):

            text = chunk.get("text", "")
            metadata = chunk.get("metadata", {})

            file_metadata = metadata.get(
                "metadata",
                {}
            )

            filename = file_metadata.get(
                "filename",
                "Unknown source"
            )

            evidence_sections.append(
                f"[Evidence {index}]\n"
                f"Source: {filename}\n"
                f"Content: {text}"
            )

        evidence = "\n\n".join(evidence_sections)

        prompt = f"""
You are an AI assistant supporting authorized investigators.

Your task is to answer the user's question using ONLY the provided investigation evidence.

Follow these rules carefully:

1. Do not use outside knowledge or assumptions.

2. Identify the investigation case, person, event, date, or other specific context
   mentioned in the user's question before answering.

3. If the user's question does NOT specify an investigation case, check whether
   the provided evidence belongs to multiple investigation cases.

4. If the provided evidence contains multiple investigation cases and the user
   did not specify a case, DO NOT summarize or answer using those cases.
   Instead, respond only that the question is ambiguous and ask the user to
   specify the investigation case.

5. When asking the user to specify a case, mention the relevant case numbers
   found in the evidence when available.

6. When the user specifies an investigation case, use ONLY evidence belonging
   to that case. Do not use evidence from other investigation cases unless the
   user explicitly asks for a comparison or the evidence explicitly establishes
   that the cases are related.

7. Prefer evidence that directly answers the user's question within the correct
   investigation case.

8. If the evidence for the specified case does not contain the requested
   information, clearly state that the available evidence is insufficient.

9. Do not invent, infer, or guess missing information.

10. Do not treat similar events in different investigation cases as the same event.

11. When answering, mention the source document when useful.

Investigation Evidence:
{evidence}

User Question:
{query}

Answer:
""".strip()

        return prompt

    def build_cdr_prompt(
        self,
        query: str,
        cdr_data: dict
    ) -> str:

        if not isinstance(query, str):
            raise ValueError("Query must be a string.")

        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if not isinstance(cdr_data, dict):
            raise ValueError("cdr_data must be a dictionary.")

        prompt = f"""
You are an AI assistant supporting authorized investigators.

Answer the user's question using ONLY the provided CDR analysis.

Follow these rules carefully:

1. Do not use outside knowledge or assumptions.

2. Base your answer only on the CDR data provided below.

3. The target phone number is explicitly identified in the
   CDR Analysis as "target_number".

4. NEVER confuse the target phone number with another phone
   number appearing as a contact in the CDR analysis.

5. Clearly distinguish between factual communication statistics
   and potential irregular communication patterns.

6. If the CDR analysis identifies an irregular or potentially
   suspicious pattern, describe what the data shows without
   automatically claiming that the person committed wrongdoing.

7. Do not invent missing information.

8. If the provided CDR data does not contain enough information
   to answer the question, clearly state that the available CDR
   data is insufficient.

9. Use specific numbers, dates, contacts, frequencies, or
   durations from the CDR data when relevant.

10. Treat suspicious or irregular communication patterns as
    indicators for further investigation, not proof of wrongdoing.

11. Do not calculate, invent, or infer statistics that are not explicitly
    provided in the CDR Analysis.

12. For numeric values such as total interactions, incoming calls,
    outgoing calls, duration, and contact frequency, use the exact
    values provided in the CDR Analysis.

13. Do not introduce additional statistics such as longest call,
    average duration, or percentage unless those statistics are
    explicitly provided in the CDR Analysis.

14. Treat the CDR Analysis as the authoritative source for all
    communication statistics.

15. The fields "incoming_interactions" and "outgoing_interactions"
    describe the direction of communication relative to the target
    phone number. Do not reinterpret these fields.

16. "incoming_interactions" means interactions received by the target
    number.

17. "outgoing_interactions" means interactions made by the target
    number.

18. Do not generate Python code, SQL code, or other code in the answer.
    Answer the user's question directly using the provided CDR Analysis.

19. Do not calculate or invent statistics that are not explicitly
    present in the CDR Analysis.

20. Do not introduce statistics such as longest call, average duration,
    percentages, or other measurements unless they are explicitly
    provided.

21. When a list such as "most_frequent_contacts" is provided, preserve
    its ordering. The first contact has the highest interaction count
    among the provided contacts.

22. Use the exact numerical values provided in the CDR Analysis.

23. The "target_number" is the phone number being analyzed.
    Always use the exact value provided.

24. Never shorten, modify, remove, or alter any digit of the
    target_number.

25. The "contact_number" identifies another phone number that
    communicated with the target. It is NOT the target number.

26. For irregular-pattern queries, the CDR Analysis already contains
    the results of the pattern detection. Report and summarize only
    the patterns provided.

27. Do not recalculate, reinterpret, or invent irregular patterns
    or statistics.

28. Use the exact contact numbers, dates, counts, ratios, and other
    evidence values provided in the CDR Analysis.

29. If "total_patterns_detected" is greater than zero, state that
    irregular communication patterns were detected and summarize the
    relevant pattern types and examples.

30. If "total_patterns_detected" is zero, state that no irregular
    communication patterns were detected in the analyzed CDR data.

31. Treat irregular or suspicious patterns as indicators for further
    investigation, not proof of wrongdoing.

32. For irregular-pattern queries, present the answer in this structure:

    - Start with whether irregular patterns were detected and state
      the exact target phone number.
    - State the total number of detected patterns.
    - Provide a concise bullet list of each detected pattern type
      and its exact count.
    - Provide one or two representative examples when available.
    - End by stating that irregular patterns are indicators for
      further investigation and are not proof of wrongdoing.

33. Do not unnecessarily explain the meaning of each pattern type
    if the pattern description is already clear from the CDR Analysis.

34. Do not list every detected pattern individually when the CDR
    Analysis provides pattern_counts and representative_patterns.
    Summarize the counts and use only representative examples.

35. Keep the response concise and focused on findings relevant to
    the investigator.

36. When giving an example, use the exact contact number, date,
    interaction count, ratio, or other evidence provided in the
    CDR Analysis.

37. Do not state that a communication "occurred" at unusual hours
    unless the CDR Analysis explicitly provides the relevant
    communication time. If only the pattern classification is
    provided, describe it as a detected pattern rather than
    inventing a specific time.

38. For communication-timeline queries, the CDR Analysis has already
    generated and summarized the timeline. Do not perform filtering,
    programming, SQL, or additional data processing.

39. Report the timeline information directly from the CDR Analysis.

40. Do not generate Python, JavaScript, SQL, or any other code.

41. Do not invent communication records, dates, times, contacts,
    durations, or statistics.

42. When reporting the timeline period, use the exact
    "timeline_start" and "timeline_end" values provided.

43. When reporting first or last communications, use only the
    records provided under "first_5_communications" and
    "last_5_communications".

44. When reporting busiest communication dates, use only the dates
    and interaction counts provided under
    "busiest_communication_dates".

45. Do not attempt to filter the timeline using the target number.
    The backend has already identified the communications belonging
    to the target number.

46. The "contact_number" in a timeline record is the other party
    involved in the communication. It is not the target number.

47. Preserve the exact target_number provided in the CDR Analysis.

48. When reporting "first_5_communications" or "last_5_communications",
    describe them as the first or last five records in the timeline.
    Do not describe them as the total communications for that date.

49. Do not combine or aggregate the first or last five records unless
    the CDR Analysis explicitly provides an aggregate value.

50. For communication-network queries:
- Report the total contacts and interactions from the supplied analysis.
- List only the contacts included in top_contacts.
- Use the exact interaction counts, duration statistics, and timestamps provided.
- Do not independently calculate or invent statistics.
- Do not claim that the displayed top contacts represent the complete network.

TARGET PHONE NUMBER BEING ANALYZED:

{cdr_data["target_number"]}

This is the exact target number. Do not modify any digit.

CDR Analysis:

{json.dumps(cdr_data, indent=2, default=str)}

User Question:

{query}

Answer:
""".strip()

        return prompt


    def build_relationship_prompt(
        self,
        query: str,
        relationship_data: dict
    ) -> str:
        if not isinstance(query, str):
            raise ValueError("Query must be a string.")

        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if not isinstance(relationship_data, dict):
            raise ValueError("relationship_data must be a dictionary.")

        prompt = f"""
You are an AI assistant supporting authorized investigators.

Answer the user's question using ONLY the provided Relationship
Mapping API data.

Follow these rules carefully:

1. Do not use outside knowledge or assumptions.

2. Treat the provided relationship data as the authoritative
   source for family relationships.

3. Identify the target person using the "target" field.
   Do not confuse the target person with their relatives.

4. Explain relationships accurately using the relationship types
   and other fields provided in the data.

5. When a relationship includes a "side" field, distinguish
   between the TARGET side and the SPOUSE side.

6. When a relationship includes a "relatedTo" field, use it
   to explain which person the relationship is associated with.

7. Respect the requested relationship degree. Do not claim that
   a person belongs to a degree unless supported by the data.

8. If the user requests a complete family tree, summarize the
   relationships available in the supplied data without claiming
   that it contains every possible relative.

9. Do not invent missing names, citizen IDs, relationships,
   family connections, or other details.

10. If a field is null, missing, or unavailable, state that the
    information is not available in the provided data.

11. If the data does not contain enough information to answer
    the question, clearly state that the available relationship
    data is insufficient.

12. Do not interpret family relationships as evidence of
    corruption, criminal activity, or wrongdoing.

13. Keep the answer concise, structured, and relevant to
    the investigator's question.

Relationship Mapping API Data:

{json.dumps(relationship_data, indent=2, default=str, ensure_ascii=False)}

User Question:

{query}

Answer:
""".strip()

        return prompt