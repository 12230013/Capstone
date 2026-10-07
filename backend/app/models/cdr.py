from datetime import datetime

from pydantic import BaseModel, Field

class CDRRecord(BaseModel):
    datetime: datetime
    calling_number: str
    called_number: str
    called_party_name: str
    called_party_cid: str
    service: str
    duration: str
    duration_seconds: int
    called_number_freq: int


class CDRSummaryResponse(BaseModel):
    success: bool
    records: list[CDRRecord]