from datetime import date, time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Path

from app.api.routes.validators import validate_target_number
from app.services.cdr_service import CDRService
from app.analytics.cdr_analytics import (
    analyze_communication_direction,
    analyze_interactions,
    detect_irregular_patterns,
    filter_records,
    generate_communication_network,
    generate_communication_timeline,
)

router = APIRouter(prefix="/api/cdr", tags=["CDR"])
cdr_service = CDRService()

PatternType = Literal[
    "HIGH_FREQUENCY",
    "ONE_SIDED_INCOMING",
    "ONE_SIDED_OUTGOING",
    "REPEATED_SHORT_CALLS",
    "UNUSUAL_COMMUNICATION_HOURS",
    "COMMUNICATION_SPIKE",
]


async def get_cdr_summary(number: str):
    """Retrieve raw CDR records and normalize upstream errors."""
    try:
        result = await cdr_service.get_summary(number)
        if not getattr(result, "records", None):
            raise HTTPException(status_code=404, detail="No CDR records found for this number.")
        return result
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="CDR service timed out.")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}.",
        )
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Unable to connect to the CDR service.")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def validate_filters(
    start_date: date | None,
    end_date: date | None,
    start_time: time | None,
    end_time: time | None,
    direction: str | None,
):
    # Both dates must be provided together
    if (start_date is None) != (end_date is None):
        raise HTTPException(
            status_code=400,
            detail="Both start_date and end_date must be provided together.",
        )

    # Start date cannot be later than end date
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="Invalid date range. start_date cannot be later than end_date.",
        )

    # Reject equal times when both are supplied
    if (
        start_time is not None
        and end_time is not None
        and start_time == end_time
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid time range. start_time and end_time cannot be equal.",
        )

    # Validate communication direction
    if direction is not None and direction not in ("incoming", "outgoing"):
        raise HTTPException(
            status_code=400,
            detail="Invalid direction. Allowed values are 'incoming' or 'outgoing'.",
        )

async def get_filtered_records(
    number: str,
    start_date: date | None = None,
    end_date: date | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    direction: str | None = None,
    contact_number: str | None = None,
):
    validate_filters(start_date, end_date, start_time, end_time, direction)
    if contact_number is not None:
        if not contact_number.isascii() or not contact_number.isdigit():
            raise HTTPException(
                status_code=400,
                detail="Invalid contact_number. It must contain digits only.",
            )

        if len(contact_number) != 8:
            raise HTTPException(
                status_code=400,
                detail="Invalid contact_number. It must be exactly 8 digits.",
            )
    summary = await get_cdr_summary(number)
    records = filter_records(
        summary.records,
        number,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        direction=direction,
        contact_number=contact_number,
    )
    return summary, records


# 1. Comprehensive summary: direction totals + contact frequency/interactions
@router.get("/summary/{number}")
async def get_comprehensive_cdr_summary(
    number: str = Depends(validate_target_number),
):
    """
    Comprehensive CDR summary containing:
    - Total records and unique contacts
    - Incoming/outgoing communication statistics
    - Contact frequency analysis
    - Top contacts
    - Data coverage
    """

    summary = await get_cdr_summary(number)
    records = summary.records

    # Overall incoming/outgoing statistics
    direction = analyze_communication_direction(records, number)

    # Per-contact statistics, sorted by total_interactions descending
    contacts = analyze_interactions(records, number)

    # Build per-contact frequency, preserving the original CDR frequency field
    contact_frequency = []

    for contact in contacts:
        contact_number = contact.get("contact_number")

        # Find records associated with this contact
        matching_records = [
            record
            for record in records
            if (
                record.calling_number == number
                and record.called_number == contact_number
            )
            or (
                record.calling_number == contact_number
                and record.called_number == number
            )
        ]

        # Preserve called_number_freq from the original CDR records.
        # Use the most recent matching record that has a frequency value.
        frequency_records = [
            record for record in matching_records
            if getattr(record, "called_number_freq", None) is not None
        ]

        called_number_freq = (
            frequency_records[-1].called_number_freq
            if frequency_records
            else None
        )

        contact_frequency.append({
            "contact_number": contact.get("contact_number"),
            "contact_name": contact.get("contact_name"),
            "contact_cid": contact.get("contact_cid"),

            # Original CDR system field
            "called_number_freq": called_number_freq,

            # Calculated analytics
            "total_interactions": contact.get("total_interactions", 0),
            "incoming_interactions": contact.get("incoming_interactions", 0),
            "outgoing_interactions": contact.get("outgoing_interactions", 0),
            "total_duration_seconds": contact.get("total_duration_seconds", 0),
            "first_communication": contact.get("first_communication"),
            "last_communication": contact.get("last_communication"),
            "average_duration_seconds": contact.get("average_duration_seconds", 0),
        })

    contact_frequency.sort(
        key=lambda item: item["total_interactions"],
        reverse=True,
    )

    # Find the first and last record timestamps
    timestamps = [
        record.datetime for record in records
        if getattr(record, "datetime", None) is not None
    ]

    data_coverage = {
        "first_record": min(timestamps).isoformat() if timestamps else None,
        "last_record": max(timestamps).isoformat() if timestamps else None,
    }

    return {
        "success": True,
        "target_number": number,
        "total_records": len(records),
        "total_contacts": len(contacts),

        # Overall communication statistics
        "communication_direction": direction,

        # Per-contact frequency analysis
        "contact_frequency": contact_frequency,

        # Keep these existing fields for frontend compatibility
        "contacts": contacts,
        "top_contacts": contacts[:10],

        # Period covered by the available CDR records
        "data_coverage": data_coverage,
    }


# 2. Records endpoint: optional date/time/direction/contact filters and statistics
@router.get("/records/{number}")
async def get_cdr_records(
    number: str = Depends(validate_target_number),
    start_date: date | None = Query(default=None, description="Must be used with end_date."),
    end_date: date | None = Query(default=None, description="Must be used with start_date."),
    start_time: time | None = Query(default=None, description="24-hour time, e.g. 00:00."),
    end_time: time | None = Query(default=None, description="Exclusive end time, e.g. 06:00."),
    direction: str | None = Query(default=None),
    contact_number: str | None = Query(default=None),
):
    _, records = await get_filtered_records(
        number, start_date, end_date, start_time, end_time, direction, contact_number
    )
    contacts = analyze_interactions(records, number)
    return {
        "success": True,
        "target_number": number,
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "direction": direction,
            "contact_number": contact_number,
        },
        "total_records": len(records),
        "statistics": analyze_communication_direction(records, number),
        "total_contacts": len(contacts),
        "contacts": contacts,
        "records": records,
    }


# 3. Chronological timeline, with the same filter options
@router.get("/timeline/{number}")
async def get_cdr_timeline(
    number: str = Depends(validate_target_number),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    start_time: time | None = Query(default=None),
    end_time: time | None = Query(default=None),
    direction: str | None = Query(default=None),
    contact_number: str | None = Query(default=None),
):
    _, records = await get_filtered_records(
        number, start_date, end_date, start_time, end_time, direction, contact_number
    )
    timeline = generate_communication_timeline(records, number)
    return {
        "success": True,
        "target_number": number,
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "direction": direction,
            "contact_number": contact_number,
        },
        "total_interactions": len(timeline),
        "timeline": timeline,
    }

# 4. Pattern analysis. Pattern-specific queries are supported through pattern_type.
@router.get("/patterns/{number}")
async def get_cdr_patterns(
    number: str = Depends(validate_target_number),
    pattern_type: PatternType | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    validate_filters(start_date, end_date, None, None, None)
    _, records = await get_filtered_records(
        number, start_date=start_date, end_date=end_date
    )
    patterns = detect_irregular_patterns(records, number)
    if pattern_type:
        patterns = [p for p in patterns if p["pattern_type"] == pattern_type]
    return {
        "success": True,
        "target_number": number,
        "pattern_type": pattern_type,
        "period": {"start_date": start_date, "end_date": end_date},
        "total_patterns": len(patterns),
        "patterns": patterns,
        "note": "These rule-based patterns are indicators for investigator review, not proof of wrongdoing.",
    }

# 5. Network data for visualization
@router.get("/network/{number}")
async def get_cdr_network(
    number: str = Depends(validate_target_number),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    validate_filters(start_date, end_date, None, None, None)
    _, records = await get_filtered_records(
        number, start_date=start_date, end_date=end_date
    )
    return {
        "success": True,
        "target_number": number,
        "network": generate_communication_network(records, number),
    }
