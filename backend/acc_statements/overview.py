"""Balanced source context for broad overviews; no extra embedding/model calls."""
import re
from acc_statements.ingest import load_docs


def overview_hits(question, hits, case_nos=None, max_chars=5500):
    if not hits or not re.search(r"tell me about|overview|summari[sz]|summary|who.*involv", question, re.I):
        return hits
    docs = load_docs()
    if case_nos is not None:
        docs = [doc for doc in docs if doc.get("header", {}).get("case_no") in case_nos]
    query = question.casefold()
    named = [doc for doc in docs if doc.get("header", {}).get("name", "").strip()
             and doc["header"]["name"].strip().casefold() in query]
    if named:
        selected = named
    else:
        # Resolve informal case labels from the source text, never a hard-coded alias.
        match = re.search(r"\b(?:about|in|of)\s+(?:the\s+)?([\w -]+?)\s+case\b", query)
        label = match.group(1).strip() if match else ""
        matched = [doc for doc in docs if label and re.search(
            rf"\b{re.escape(label)}\b",
            " ".join(str(value) for value in doc.get("header", {}).values()) + " " +
            " ".join(s["text"] for s in doc.get("sentences", [])), re.I)]
        cases = {doc.get("header", {}).get("case_no") for doc in matched}
        cases.discard(None)
        cases.discard("")
        selected = [doc for doc in docs if doc.get("header", {}).get("case_no") in cases] if cases else []
    if not selected:
        return hits
    selected = [doc for doc in selected if doc.get("sentences")]
    if not selected:
        return hits
    budget = max_chars // len(selected)
    result = []
    for doc in selected:
        rows = doc["sentences"]
        relevant = {sid for hit in hits if hit.get("doc_id") == doc["doc_id"] for sid in hit.get("sentence_ids", [])}
        # Interleave coverage from beginning to end with semantic matches.
        # Visit both ends and the middle before filling in gaps. Ordered sampling
        # otherwise exhausts the budget before reaching late payment/admission passages.
        spread = list(dict.fromkeys(round(i * (len(rows) - 1) / 11)
                                   for i in (0, 11, 6, 3, 9, 1, 10, 4, 8, 2, 7, 5)))
        ranked = []
        matches = [i for i, row in enumerate(rows) if row["id"] in relevant]
        for i in range(max(len(spread), len(matches))):
            if i < len(spread): ranked.append(spread[i])
            if i < len(matches): ranked.append(matches[i])
        chosen, size = [], 0
        for index in dict.fromkeys(ranked):
            cost = len(rows[index]["text"]) + len(rows[index]["id"]) + 4
            if size + cost <= budget:
                chosen.append(index)
                size += cost
        if not chosen:
            continue
        chosen.sort()
        header = doc.get("header", {})
        result.append({"doc_id": doc["doc_id"], "person_name": header.get("name", ""),
            "case_no": header.get("case_no", ""), "statement_date": header.get("statement_date", ""),
            "sentence_ids": [rows[i]["id"] for i in chosen],
            "text_numbered": "\n".join(f"[{rows[i]['id']}] {rows[i]['text']}" for i in chosen)})
    return result or hits
