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

            filename = metadata.get(
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

3. If the user's question does NOT specify an investigation case or other context,
   check whether the retrieved evidence contains information from multiple
   investigation cases.

4. If multiple investigation cases contain potentially relevant information and
   the user did not specify which case they mean, DO NOT choose one case
   arbitrarily. State that the question is ambiguous and ask the user to specify
   the investigation case.

5. Do not combine facts from different investigation cases unless the evidence
   explicitly establishes that they are related.

6. When the user specifies an investigation case, use evidence belonging to that
   case and ignore unrelated cases unless they are explicitly relevant.

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