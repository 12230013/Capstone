from typing import Literal
from pydantic import BaseModel


# ----- summary -----
class KeyPoint(BaseModel):
    point: str
    sentence_ids: list[str]


class StatementSummary(BaseModel):
    summary: str
    key_points: list[KeyPoint]


# ----- entities -----
EntityType = Literal["PERSON", "ORGANIZATION", "LOCATION", "DATE", "TIME", "MONEY",
                     "PHONE_NUMBER", "VEHICLE", "DOCUMENT", "EVENT", "OTHER"]


class Entity(BaseModel):
    type: EntityType
    value: str
    role_or_context: str
    sentence_id: str
    evidence_quote: str


class EntityList(BaseModel):
    entities: list[Entity]


# ----- timeline -----
class TimelineEvent(BaseModel):
    date_text: str          # words exactly as in statement ("12 March 2024", "last Tuesday"); "" if none
    time_text: str          # "2 pm", "evening"; "" if none
    event: str
    people: list[str]
    location: str
    sentence_id: str
    evidence_quote: str


class TimelineExtraction(BaseModel):
    events: list[TimelineEvent]


# ----- contradictions -----
ClaimTopic = Literal["PRESENCE_LOCATION", "TIME_DATE", "AMOUNT_QUANTITY", "PERSON_INVOLVED",
                     "ACTION_EVENT", "COMMUNICATION", "OBJECT_DOCUMENT", "RELATIONSHIP", "OTHER"]


class Claim(BaseModel):
    topic: ClaimTopic
    claim: str              # one self-contained factual assertion
    sentence_id: str
    evidence_quote: str


class ClaimList(BaseModel):
    claims: list[Claim]


class Verdict(BaseModel):
    relation: Literal["CONTRADICTION", "DIFFERENT_DETAIL", "CONSISTENT", "UNRELATED"]
    explanation: str
    detail_a: str
    detail_b: str