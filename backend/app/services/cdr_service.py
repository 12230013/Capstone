import httpx

from app.config import settings
from app.models.cdr import (
    CDRRecord,
    CDRSummaryResponse
)
from app.utils.cdr_utils import duration_to_seconds


class CDRService:

    def __init__(self):
        self.base_url = settings.cdr_api_base_url.rstrip("/")
        self.timeout = settings.cdr_api_timeout

    async def get_summary(
        self,
        number: str
    ) -> CDRSummaryResponse:

        url = f"{self.base_url}/api/summary/{number}"

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.get(url)

            response.raise_for_status()

            data = response.json()

        if not isinstance(data, dict):
            raise ValueError(
                "Invalid CDR API response"
            )

        if data.get("success") is not True:
            raise ValueError(
                "CDR API reported an unsuccessful request"
            )

        records = data.get("records")

        if not isinstance(records, list):
            raise ValueError(
                "Invalid records format"
            )

        normalized_records = []

        for record in records:

            normalized_record = CDRRecord(
                datetime=record["datetime"],
                calling_number=record["calling_number"],
                called_number=record["called_number"],
                called_party_name=record["called_party_name"],
                called_party_cid=record["called_party_cid"],
                service=record["service"],
                duration=record["duration"],
                duration_seconds=duration_to_seconds(
                    record["duration"]
                ),
                called_number_freq=record["called_number_freq"]
            )

            normalized_records.append(
                normalized_record
            )

        if not normalized_records:
            raise ValueError(
              f"No CDR records found for phone number {number}."
        )

        return CDRSummaryResponse(
            success=True,
            records=normalized_records
        )