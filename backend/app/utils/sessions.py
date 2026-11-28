"""Revocable server-side sessions. The browser receives an HttpOnly cookie."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import HTTPException, Request, Response

from app.config import settings
from app.database.connection import sessions_collection, users_collection

COOKIE_NAME = "acc_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def allowed_origins():
    return [origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip()]


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin not in allowed_origins():
        raise HTTPException(403, "This request origin is not allowed.")


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def public_user(user):
    return {"id": str(user["_id"]), **{
        key: user.get(key, "") for key in ("name", "employee_id", "email", "role", "department")
    }}


def cookie_options():
    secure = settings.session_cookie_secure
    if secure is None:
        secure = settings.environment == "production"
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/api",
    }


def create_session(user_id: str, response: Response):
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=settings.session_hours)
    sessions_collection.insert_one({
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "csrf_token": csrf_token, "user_id": user_id,
        "created_at": now, "last_seen_at": now, "expires_at": expires_at, "ended_at": None,
    })
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_hours * 3600, **cookie_options())
    response.headers["Cache-Control"] = "no-store"
    return csrf_token


def clear_session_cookie(response: Response):
    response.delete_cookie(COOKIE_NAME, **cookie_options())
    response.headers["Cache-Control"] = "no-store"


def require_session(request: Request):
    if hasattr(request.state, "session"):
        return request.state.session
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Please sign in to continue.")
    if sessions_collection is None or users_collection is None:
        raise HTTPException(503, "Database connection is not available.")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = sessions_collection.find_one({"token_hash": token_hash, "ended_at": None})
    now = datetime.now(timezone.utc)
    idle_cutoff = now - timedelta(minutes=settings.session_idle_minutes)
    if (
        session is None or not session.get("expires_at") or not session.get("last_seen_at")
        or utc(session["expires_at"]) <= now or utc(session["last_seen_at"]) <= idle_cutoff
    ):
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    if request.method not in SAFE_METHODS:
        check_origin(request)
        provided = request.headers.get("X-CSRF-Token", "")
        if not provided or not secrets.compare_digest(provided.encode(), session.get("csrf_token", "").encode()):
            raise HTTPException(403, "Session verification failed. Refresh the page and try again.")
    if not ObjectId.is_valid(session["user_id"]):
        raise HTTPException(401, "Please sign in again.")
    user = users_collection.find_one({"_id": ObjectId(session["user_id"])}, {"password": 0})
    if user is None:
        raise HTTPException(401, "This account is no longer available.")
    # Automatic sidebar polling must not keep an unattended session alive.
    seen_at = session["last_seen_at"] if request.headers.get("X-Session-Activity") == "background" else now
    updated = sessions_collection.update_one({
        "_id": session["_id"], "ended_at": None,
        "expires_at": {"$gt": now}, "last_seen_at": {"$gt": idle_cutoff},
    }, {"$max": {"last_seen_at": seen_at}})
    if not updated.matched_count:
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    session["user"] = public_user(user)
    session["presentation_access"] = user.get("presentation_access")
    request.state.session = session
    return session


def check_user_id(user_id, session):
    if user_id and user_id != session["user_id"]:
        raise HTTPException(403, "You cannot access another account's data.")
    return session["user_id"]
