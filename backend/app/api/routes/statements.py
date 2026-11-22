from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.services.statement_service import StatementService

router = APIRouter(
    prefix="/api/statements",
    tags=["ACC Statements"],
)

statement_service = StatementService()


class StatementQueryRequest(BaseModel):
    query: str
    limit: Optional[int] = 4
    case_nos: Optional[List[str]] = None


class ContradictionRequest(BaseModel):
    statement_ids: Optional[List[str]] = None


@router.get("/")
def list_statements():
    """
    List all ACC statement documents with extracted person and case metadata.
    """
    try:
        statements = statement_service.list_statements()
        return {
            "success": True,
            "count": len(statements),
            "statements": statements
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeline")
def get_timeline(case_no: Optional[str] = Query(None, description="Optional case number filter")):
    """
    Builds a chronological timeline of events across witness and suspect statements.
    """
    try:
        timeline = statement_service.build_timeline(case_no=case_no)
        return {
            "success": True,
            "count": len(timeline),
            "timeline": timeline
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{statement_id}")
def get_statement_details(statement_id: str):
    """
    Retrieve full parsed text and metadata for a specific statement.
    """
    try:
        statement = statement_service.get_statement(statement_id)
        return {
            "success": True,
            "statement": statement
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{statement_id}/summary")
def get_statement_summary(statement_id: str):
    """
    Retrieve concise analytical summary and key points with sentence citations.
    """
    try:
        result = statement_service.summarize_statement(statement_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
def ingest_statements():
    """
    Ingest and index all statement documents into Qdrant for RAG search.
    """
    try:
        result = statement_service.ingest_statements()
        return {
            "success": True,
            "message": "Statements successfully indexed into vector database.",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
def query_statements(payload: StatementQueryRequest):
    """
    Perform semantic RAG retrieval and Q&A specifically over ACC statements.
    Includes sentence-level citations like [stmt_01-s4] and citation verification.
    """
    try:
        result = statement_service.query_statement_evidence(
            query=payload.query,
            limit=payload.limit or 4,
            case_nos=payload.case_nos
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/contradictions")
def detect_contradictions(payload: Optional[ContradictionRequest] = None):
    """
    Detect factual contradictions and metadata inconsistencies across statements.
    """
    try:
        ids = payload.statement_ids if payload else None
        result = statement_service.detect_contradictions(statement_ids=ids)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# Compatibility aliases for acc_statements/api.py routes
# -------------------------------------------------------------
@router.post("/v1/summarization/document/{doc_id}")
def api_v1_summary(doc_id: str):
    return statement_service.summarize_statement(doc_id)


@router.get("/v1/cases/{case_no:path}/timeline")
def api_v1_timeline(case_no: str):
    return statement_service.build_timeline(case_no=case_no)


@router.get("/v1/cases/{case_no:path}/inconsistencies")
def api_v1_inconsistencies(case_no: str):
    return statement_service.detect_contradictions()


@router.post("/v1/rag/query")
def api_v1_rag(payload: StatementQueryRequest):
    return statement_service.query_statement_evidence(query=payload.query, case_nos=payload.case_nos)
