from datetime import datetime, timezone
from app.utils.sessions import require_session, clear_session_cookie
from fastapi import APIRouter, Depends, Response, Query
from app.database.connection import activity_collection, sessions_collection

router = APIRouter(prefix="/api", tags=["Activity"])


@router.get("/activity")
def list_activity(limit: int = Query(100, ge=1, le=200), session: dict = Depends(require_session)):
    events = activity_collection.find({"user_id": session["user_id"]}).sort("created_at", -1).limit(limit)
    result = []
    for event in events:
        date = event["created_at"]
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        result.append({
            "id": str(event["_id"]), "type": event["type"],
            "created_at": date.isoformat(), "query": event.get("query"),
            "ip_address": event.get("ip_address"), "sources": event.get("sources", []),
        })
    return {"activities": result}


@router.post("/auth/logout")
def logout(response: Response, session: dict = Depends(require_session)):
    clear_session_cookie(response)
    now = datetime.now(timezone.utc)
    updated = sessions_collection.update_one({"_id": session["_id"], "ended_at": None}, {"$set": {"ended_at": now}})
    if updated.modified_count:
        activity_collection.insert_one({"user_id": session["user_id"], "type": "session_end", "created_at": now})
    return {"success": True}
