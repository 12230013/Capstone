from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

try:
    from analyze import build_case_timeline, extract_entities, summarize
    from chat import ask
    from contradictions import detect_contradictions
    from ingest import load_docs
except (ImportError, ModuleNotFoundError):
    from acc_statements.analyze import build_case_timeline, extract_entities, summarize
    from acc_statements.chat import ask
    from acc_statements.contradictions import detect_contradictions
    from acc_statements.ingest import load_docs

app = FastAPI(title="ACC Statement Analysis (prototype)")

# PROTOTYPE ONLY: replace with real JWT + case-assignment lookup from CIMS/PostgreSQL
USER_CASES = {"demo-investigator": ["ACC/2024/017"], "demo-admin": None}   # None = all cases


def allowed_cases(user: str):
    if user not in USER_CASES:
        raise HTTPException(401, "Unknown user")
    return USER_CASES[user]


def docs_for(user: str, case_no: str | None = None):
    allowed = allowed_cases(user)
    docs = [d for d in load_docs() if allowed is None or d["header"].get("case_no") in allowed]
    if case_no:
        docs = [d for d in docs if d["header"].get("case_no") == case_no]
    if not docs:
        raise HTTPException(403, "No accessible statements for this case")
    return docs


class RagRequest(BaseModel):
    question: str


@app.post("/api/v1/summarization/document/{doc_id}")
def api_summary(doc_id: str, x_user: str = Header(...)):
    d = next((d for d in docs_for(x_user) if d["doc_id"] == doc_id), None)
    if not d:
        raise HTTPException(404, "Document not found or not accessible")
    return {"summary": summarize(d), "entities": extract_entities(d)}


@app.get("/api/v1/cases/{case_no:path}/timeline")
def api_timeline(case_no: str, x_user: str = Header(...)):
    return build_case_timeline(docs_for(x_user, case_no))


@app.get("/api/v1/cases/{case_no:path}/inconsistencies")
def api_inconsistencies(case_no: str, x_user: str = Header(...)):
    return detect_contradictions(docs_for(x_user, case_no))


@app.post("/api/v1/rag/query")
def api_rag(req: RagRequest, x_user: str = Header(...)):
    allowed = allowed_cases(x_user)
    return ask(req.question, case_nos=allowed)