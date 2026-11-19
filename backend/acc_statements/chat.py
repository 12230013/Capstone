try:
    from acc_statements import config
    from acc_statements.index import search
except (ImportError, ModuleNotFoundError):
    import config
    from index import search


def ask(question: str, case_nos=None) -> dict:
    from app.services.evidence_grounding import answer_document_question, numbered_sentences
    from app.services.llm_service import LLMService
    hits = search(question, case_nos=case_nos)
    from acc_statements.overview import overview_hits
    hits = overview_hits(question, hits, case_nos=case_nos)
    sentences = {}
    for hit in hits:
        sentences.update(numbered_sentences(hit.get("text_numbered", "")))
    context = "\n".join(dict.fromkeys(
        f"{hit['doc_id']}: statement by {hit.get('person_name', 'Unknown')}, "
        f"case {hit.get('case_no', '')}, dated {hit.get('statement_date', '')}"
        for hit in hits
    ))
    grounded = answer_document_question(question, sentences, LLMService().generate, document_context=context)
    sources = []
    cited = set(grounded["sentence_ids"])
    for hit in hits:
        ids = [key for key in hit.get("sentence_ids", []) if key in cited]
        if not ids:
            continue
        sources.append({
            "doc_id": hit["doc_id"], "filename": hit["doc_id"] + ".txt",
            "person_name": hit.get("person_name", ""), "case_no": hit.get("case_no", ""),
            "statement_date": hit.get("statement_date", ""), "sentence_ids": ids,
            "excerpt": "\n".join(f"[{key}] {sentences[key]}" for key in ids),
        })
    return {"answer": grounded["answer"], "sources": sources, "warnings": [], "disclaimer": config.DISCLAIMER}


def retrieve_evidence(question: str, case_nos=None) -> dict:
    """Retrieve statement records for combined analysis without generating an answer."""
    hits = search(question, case_nos=case_nos)
    if not hits:
        return {"success": True, "evidence": [], "warnings": ["No accessible statements matched."]}
    evidence = []
    for hit in hits:
        evidence.append({
            "source_type": "statement",
            "statement_id": hit.get("doc_id"),
            "person_name": hit.get("person_name"),
            "statement_date": hit.get("statement_date"),
            "case_no": hit.get("case_no"),
            "retrieval_score": hit.get("score"),
            "text": hit.get("text_numbered", ""),
        })
    return {"success": True, "evidence": evidence, "warnings": []}

