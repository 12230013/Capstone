"""Shared case-scoped authorization for external investigation APIs."""
from fastapi import Depends, HTTPException, Request

from app.services.cims_service import authorize_subject, relationship_scope
from starlette.concurrency import run_in_threadpool
from app.utils.sessions import require_session


def _require_subject(request, session, parameter, mode):
    subject = request.path_params.get(parameter)
    if subject is None and request.url.path.endswith("/_ping"):
        return
    case_id = request.query_params.get("case_id")
    if not case_id or not subject:
        raise HTTPException(403, "Case access denied.")
    return authorize_subject(session, case_id, mode, subject)


def require_cdr_case(request: Request, session: dict = Depends(require_session)):
    _require_subject(request, session, "number", "cdr")


async def require_relationship_case(request: Request, session: dict = Depends(require_session)):
    subjects = await run_in_threadpool(_require_subject, request, session, "cid", "relationships")
    with relationship_scope(subjects):
        yield
