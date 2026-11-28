"""Server-provisioned access for the two presentation accounts."""
import re

from fastapi import HTTPException

HAA_SCOPE = "presentation:haa"
TOOL_SCOPE = "presentation:tools"
HAA_CASE_NUMBER = "19/25-26"


def presentation_scope(session):
    grant = session.get("presentation_access")
    return grant if isinstance(grant, dict) else None


def require_presentation_tool(session, mode):
    grant = presentation_scope(session)
    if grant is None or mode not in (grant.get("tools") or []):
        raise HTTPException(403, "Tool access denied.")


def is_haa_reference(query):
    return bool(re.search(r"\bhaa(?:\s+case)?\b|(?<!\d)19/25-26(?!\d)", query, re.I))


def presentation_request(session, query, cims_reference):
    """Select a case or a standalone tool before chat can access evidence."""
    from app.services.cims_service import infer_case_mode

    grant = presentation_scope(session)
    scope = grant["case_id"]
    if is_haa_reference(query):
        if scope != HAA_SCOPE or cims_reference not in {None, HAA_SCOPE}:
            raise HTTPException(403, "Case access denied.")
        return HAA_SCOPE, "metadata", None
    mode, subject = infer_case_mode(query)
    if cims_reference is not None and cims_reference != scope:
        raise HTTPException(403, "Case access denied.")
    if mode in {"cdr", "relationships"}:
        require_presentation_tool(session, mode)
        return TOOL_SCOPE, mode, subject
    if cims_reference is not None:
        return scope, mode, None
    return None
