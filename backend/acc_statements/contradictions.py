import numpy as np

try:
    from acc_statements import config
    from acc_statements.analyze import header_context, locate_quote, numbered
    from acc_statements.index import embed
    from acc_statements.llm import ask_json
    from acc_statements.schemas import ClaimList, Verdict
except (ImportError, ModuleNotFoundError):
    if __package__:
        raise
    import config
    from analyze import header_context, locate_quote, numbered
    from index import embed
    from llm import ask_json
    from schemas import ClaimList, Verdict

CLAIM_SYSTEM = """You extract atomic factual claims from an investigation statement.
Rules:
- Each claim = ONE self-contained assertion, with names/dates/places/amounts written out
  (replace 'he', 'there', 'that day' with the actual name/place/date if the statement makes it clear).
- Cover: who was where and when, what was said/done/given, amounts, objects, calls/messages, relationships.
- 'evidence_quote' must be copied EXACTLY from the cited sentence.
- Use only what the statement says. No inference, no opinions about guilt."""

JUDGE_SYSTEM = """You compare two claims from DIFFERENT statements in the same investigation.
Choose exactly one relation:
- CONTRADICTION: both claims cannot be true at the same time (different amount, date, place, person, sequence, or one denies what the other asserts).
- DIFFERENT_DETAIL: one claim is more specific, or one statement is silent on a point the other mentions. Not a conflict.
- CONSISTENT: they agree.
- UNRELATED: they are about different things.
Be conservative: if the difference could be explained by wording, rounding, or a different level of detail, do NOT say CONTRADICTION.
Different jobs in different years, or work after normal office hours, are not contradictions.
The same event, subject and time must be established; otherwise choose UNRELATED or DIFFERENT_DETAIL.
Examples:
- Same payment on the same date: A says 'I paid Nu. 100'; B says 'I paid Nu. 200, not Nu. 100' => CONTRADICTION.
- A gives a payment amount; B is silent about the amount => DIFFERENT_DETAIL.
- A describes a job in 2018-2022; B describes another job in 2022-2025 => not a contradiction merely because the jobs differ.
Write a short explanation. Context helps interpret the quoted sentences but does not replace their evidence.
'detail_a' / 'detail_b' = the specific conflicting values (e.g. 'Nu. 50,000' vs 'Nu. 5,000'), or '' if none."""


def metadata_checks(docs: list[dict]) -> list[str]:
    """Deterministic header checks (no LLM)."""
    issues = []
    cases = {d["header"].get("case_no", "") for d in docs}
    if len(cases) > 1:
        issues.append(f"Statements carry different case numbers: {sorted(cases)}")
    by_cid = {}
    for d in docs:
        h = d["header"]
        if h.get("cid"):
            by_cid.setdefault(h["cid"], []).append((d["doc_id"], h.get("name", ""), h.get("dob", "")))
    for cid, rows in by_cid.items():
        if len({r[1].lower() for r in rows}) > 1 or len({r[2] for r in rows}) > 1:
            issues.append(f"CID {cid} appears with different names/dates of birth: {rows}")
    return issues


def extract_claims(doc: dict) -> list[dict]:
    """Use original sentences directly: no model-generated claim array to truncate."""
    rows = doc.get("sentences", [])
    header = doc.get("header", {})
    return [{"doc_id": doc["doc_id"], "person": header.get("name", ""),
             "statement_date": header.get("statement_date", ""), "case_no": header.get("case_no", ""),
             "topic": "OTHER", "claim": row["text"], "sentence_id": row["id"],
             "quote": row["text"], "verified": True,
             "context": " ".join(r["text"] for r in rows[max(0, i-1):i+2])}
            for i, row in enumerate(rows) if row.get("text", "").strip()]

def find_candidate_pairs(claims: list[dict]) -> list[tuple[int, int, float]]:
    if len(claims) < 2:
        return []
    m = np.array(embed([c["claim"] for c in claims]))
    sim = m @ m.T
    pairs = {}
    for i, c in enumerate(claims):
        taken = 0
        for j in np.argsort(-sim[i]):
            if j == i:
                continue
            if not config.COMPARE_SAME_DOC and claims[j]["doc_id"] == c["doc_id"]:
                continue
            if claims[j].get("case_no") != c.get("case_no"):
                continue
            if sim[i, j] < config.CLAIM_PAIR_THRESHOLD:
                break
            pairs[(min(i, j), max(i, j))] = float(sim[i, j])
            taken += 1
            if taken >= config.CLAIMS_PER_NEIGHBOUR:
                break
    ranked = sorted(pairs.items(), key=lambda kv: -kv[1])[:config.MAX_PAIRS]
    return [(i, j, s) for (i, j), s in ranked]


def judge_pair(a: dict, b: dict) -> Verdict:
    user = (f"CLAIM A (statement of {a['person']}, dated {a['statement_date']}):\n{a['claim']}\n"
            f"Quote: \"{a['quote']}\"\n\n"
            f"CLAIM B (statement of {b['person']}, dated {b['statement_date']}):\n{b['claim']}\n"
            f"Quote: \"{b['quote']}\"")
    user += f"\nContext A: {a.get('context', a['quote'])}\nContext B: {b.get('context', b['quote'])}"
    return ask_json(JUDGE_SYSTEM, user, Verdict, max_tokens=512, retries=0)


def detect_contradictions(docs: list[dict]) -> dict:
    claims = [c for d in docs for c in extract_claims(d)]
    pairs = find_candidate_pairs(claims)
    print(f"  {len(claims)} claims, {len(pairs)} candidate pairs to judge")
    flagged, details, warnings = [], [], []
    judged = 0
    for k, (i, j, s) in enumerate(pairs, start=1):
        a, b = claims[i], claims[j]
        try:
            v = judge_pair(a, b)
        except RuntimeError:
            warnings.append(f"Pair {k} could not be evaluated; no conclusion was reached for that pair.")
            continue
        judged += 1
        print(f"    pair {k}/{len(pairs)}: {v.relation}")
        if v.relation in ("CONTRADICTION", "DIFFERENT_DETAIL"):
            row = {"relation": v.relation, "similarity": round(s, 3), "explanation": v.explanation,
                   "detail_a": v.detail_a, "detail_b": v.detail_b,
                   "a": {k2: a[k2] for k2 in ("doc_id", "person", "claim", "sentence_id", "quote", "verified")},
                   "b": {k2: b[k2] for k2 in ("doc_id", "person", "claim", "sentence_id", "quote", "verified")}}
            (flagged if v.relation == "CONTRADICTION" else details).append(row)
    return {"metadata_issues": metadata_checks(docs), "contradictions": flagged,
            "different_detail": details, "claims_extracted": len(claims),
            "pairs_judged": judged, "pairs_selected": len(pairs), "warnings": warnings,
            "disclaimer": config.DISCLAIMER}
