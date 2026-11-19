"""Validation schemas for metadata received from the CIMS vendor."""
from datetime import date, time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Text = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class CIMSModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CIMSUser(CIMSModel):
    user_id: Text
    username: Text
    full_name: Text | None = None
    role: Text | None = None
    permissions: list[str] | None = None
    assigned_cases: list[str] | None = None
    is_active: bool | None = None


class CIMSEntity(CIMSModel):
    entity_id: Text
    name: Text | None = None
    cid: str | None = None
    phone_number: str | None = None
    dob: date | None = None
    nationality: str | None = None
    gender: str | None = None
    entity_type: str | None = None
    involvement: str | None = None


class CIMSInterview(CIMSModel):
    interview_id: Text
    entity_id: str | None = None
    interviewee_name: str | None = None
    interviewee_type: str | None = None
    interview_date: date | None = None
    interview_time: time | None = None
    interview_location: str | None = None
    statement_text: str | None = None
    document_ids: list[str] | None = None


class CIMSCaseEvent(CIMSModel):
    event_id: Text
    event_name: str | None = None
    event_date: date | None = None
    description: str | None = None


class CIMSDocument(CIMSModel):
    document_id: Text
    file_name: Text
    document_type: str | None = None
    file_format: str | None = None
    created_at: date | None = None
    last_updated: date | None = None


class CIMSCase(CIMSModel):
    case_id: Text
    case_number: str | None = None
    case_title: str | None = None
    case_status: str | None = None
    registered_date: date | None = None
    last_updated: date | None = None
    assigned_investigators: list[str] | None = None
    allegation_details: str | None = None
    entities: list[CIMSEntity] | None = None
    interviews: list[CIMSInterview] | None = None
    case_events: list[CIMSCaseEvent] | None = None
    documents: list[CIMSDocument] | None = None


class CIMSSyncRequest(CIMSModel):
    users: list[CIMSUser] | None = None
    cases: list[CIMSCase] | None = None

    def has_records(self) -> bool:
        return bool(self.users or self.cases)
