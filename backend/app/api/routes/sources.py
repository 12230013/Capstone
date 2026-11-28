"""Read uploaded statement files referenced by the signed-in user's chats."""
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from app.utils.sessions import require_session
from app.services.cims_documents import read_source_excerpt
from app.database.connection import conversations_collection, messages_collection
from acc_statements.config import DATA_DIR, PARSED_DIR

router = APIRouter(prefix="/api/sources", tags=["Sources"])


@router.get("/cims/{point_id}")
def get_case_source(point_id: str, case_id: str, session: dict = Depends(require_session)):
    return read_source_excerpt(session, case_id, point_id)


@router.get("/{doc_id}")
def get_source(doc_id: str, session: dict = Depends(require_session)):
    if not doc_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in doc_id):
        raise HTTPException(400, "Invalid document identifier.")
    conversation_ids = [str(c["_id"]) for c in conversations_collection.find({"user_id": session["user_id"], "case_id": None}, {"_id": 1})]
    cited = messages_collection.find_one({
        "conversation_id": {"$in": conversation_ids}, "role": "assistant",
        "sources": {"$elemMatch": {"doc_id": doc_id}},
    })
    if not cited:
        raise HTTPException(404, "Source not found in your conversations.")
    root = Path(DATA_DIR).resolve()
    path = (root / (doc_id + ".txt")).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "The original file is not available locally. You can still read the retrieved passage below.")
    sentences = []
    parsed_root = Path(PARSED_DIR).resolve()
    parsed = (parsed_root / (doc_id + ".json")).resolve()
    if parsed.parent == parsed_root and parsed.is_file():
        try:
            sentences = json.loads(parsed.read_text(encoding="utf-8")).get("sentences", [])
        except (ValueError, OSError):
            pass
    return {"filename": path.name, "text": path.read_text(encoding="utf-8-sig"), "sentences": sentences}
