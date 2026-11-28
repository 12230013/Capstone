"""Vendor-facing CIMS synchronization intake endpoint."""
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database.connection import cims_sync_collection
from app.schemas.cims import CIMSSyncRequest
from app.services.cims_service import list_cases
from app.utils.sessions import require_session

router = APIRouter(prefix="/api/cims", tags=["CIMS Integration"])
bearer = HTTPBearer(auto_error=False)
MAX_CIMS_BODY_BYTES = 1_048_576  # 1 MiB


def require_cims_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    expected = os.getenv("CIMS_API_TOKEN", "")
    supplied = credentials.credentials if credentials else ""
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid API token.", headers={"WWW-Authenticate": "Bearer"})


@router.get("/cases")
def get_cases(session: dict = Depends(require_session)):
    return {"cases": list_cases(session)}


@router.post("/sync", dependencies=[Depends(require_cims_token)])
async def sync_cims_data(
    payload: CIMSSyncRequest,
    request: Request,
    content_length: int | None = Header(default=None, alias="Content-Length"),
):
    if content_length is not None and content_length > MAX_CIMS_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body exceeds the 1 MiB limit.")

    # Also enforce the limit when Content-Length is absent or untrusted. The
    # ASGI server has already buffered the JSON body for FastAPI validation.
    if len(await request.body()) > MAX_CIMS_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body exceeds the 1 MiB limit.")
    if not payload.has_records():
        raise HTTPException(status_code=422, detail="At least one user or case is required.")
    if cims_sync_collection is None:
        raise HTTPException(status_code=500, detail="CIMS data could not be stored.")

    received_at = datetime.now(timezone.utc)
    record = {
        "sync_id": str(uuid4()),
        "received_at": received_at,
        "users": [item.model_dump(mode="json") for item in payload.users or []],
        "cases": [item.model_dump(mode="json") for item in payload.cases or []],
    }
    record["case_fingerprints"] = [
        hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()
        for case in record["cases"]
    ]
    try:
        cims_sync_collection.insert_one(record)
    except Exception:
        # Do not include database exception details or vendor data in responses/logs.
        raise HTTPException(status_code=500, detail="CIMS data could not be stored.") from None

    return {
        "status": "success",
        "message": "CIMS data received successfully",
        "users_received": len(record["users"]),
        "cases_received": len(record["cases"]),
    }
