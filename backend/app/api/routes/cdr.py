from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Path, Query

from app.services.cdr_service import CDRService

from app.analytics.cdr_analytics import (
    analyze_communication_frequency,
    analyze_communication_direction,
    filter_records_by_date,
    analyze_period_statistics,
    generate_communication_timeline,
    analyze_interactions,
    detect_irregular_patterns,
    generate_communication_network,
)

router = APIRouter(
    prefix="/api/cdr",
    tags=["CDR"],
)

cdr_service = CDRService()


# ============================================================
# Helper: Validate and retrieve CDR data
# ============================================================

async def get_cdr_summary(number: str):
    """
    Retrieve CDR records from the CDR service and
    handle common service errors.
    """

    try:
        return await cdr_service.get_summary(number)

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out",
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}",
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service",
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )


# ============================================================
# 1. CDR Summary
# GET /api/cdr/summary/{number}
# ============================================================

@router.get("/summary/{number}")
async def get_cdr_summary_endpoint(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    )
):
    """
    Retrieve all CDR records associated with a phone number.
    """

    result = await get_cdr_summary(number)

    return result


# ============================================================
# 2. Communication Frequency
# GET /api/cdr/frequency/{number}
# ============================================================

@router.get("/frequency/{number}")
async def get_cdr_frequency(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    )
):
    """
    Analyze how frequently the target number communicates
    with each contact.
    """

    summary = await get_cdr_summary(number)

    frequency = analyze_communication_frequency(
        summary.records,
        number,
    )

    return {
        "success": True,
        "target_number": number,
        "contacts": frequency,
    }


# ============================================================
# 3. Communication Direction
# GET /api/cdr/direction/{number}
# ============================================================

@router.get("/direction/{number}")
async def get_cdr_direction(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    )
):
    """
    Analyze incoming and outgoing communication
    for the target number.
    """

    summary = await get_cdr_summary(number)

    direction = analyze_communication_direction(
        summary.records,
        number,
    )

    return {
        "success": True,
        "target_number": number,
        "communication_direction": direction,
    }


# ============================================================
# 4. CDR Records by Date
# GET /api/cdr/records/{number}
# ============================================================

@router.get("/records/{number}")
async def get_cdr_records_by_date(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    ),
    start_date: date = Query(...),
    end_date: date = Query(...),
):
    """
    Retrieve CDR records within a specified date range.
    """

    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date",
        )

    summary = await get_cdr_summary(number)

    filtered_records = filter_records_by_date(
        summary.records,
        start_date,
        end_date,
    )

    return {
        "success": True,
        "target_number": number,
        "start_date": start_date,
        "end_date": end_date,
        "total_records": len(filtered_records),
        "records": filtered_records,
    }


# ============================================================
# 5. Period Statistics
# GET /api/cdr/statistics/{number}
# ============================================================

@router.get("/statistics/{number}")
async def get_cdr_period_statistics(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    ),
    start_date: date = Query(...),
    end_date: date = Query(...),
):
    """
    Calculate communication statistics for a selected period.
    """

    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date",
        )

    summary = await get_cdr_summary(number)

    result = analyze_period_statistics(
        summary.records,
        number,
        start_date,
        end_date,
    )

    return {
        "success": True,
        "target_number": number,
        "period": {
            "start_date": result["start_date"],
            "end_date": result["end_date"],
        },
        "statistics": result["statistics"],
    }


# ============================================================
# 6. Communication Timeline
# GET /api/cdr/timeline/{number}
# ============================================================

@router.get("/timeline/{number}")
async def get_cdr_timeline(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    ),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    """
    Generate a chronological communication timeline.

    Dates are optional. If one date is supplied, the other
    date must also be supplied.
    """

    # Require both dates when a date range is supplied
    if (start_date is None) != (end_date is None):
        raise HTTPException(
            status_code=400,
            detail="Provide both start_date and end_date, or neither",
        )

    # Validate date order
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date",
        )

    summary = await get_cdr_summary(number)

    timeline = generate_communication_timeline(
        summary.records,
        number,
        start_date,
        end_date,
    )

    return {
        "success": True,
        "target_number": number,
        "period": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "total_interactions": len(timeline),
        "timeline": timeline,
    }


# ============================================================
# 7. Communication Interactions
# GET /api/cdr/interactions/{number}
# ============================================================

@router.get("/interactions/{number}")
async def get_cdr_interactions(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    )
):
    """
    Analyze communication interactions between the target
    number and its contacts.
    """

    summary = await get_cdr_summary(number)

    interactions = analyze_interactions(
        summary.records,
        number,
    )

    return {
        "success": True,
        "target_number": number,
        "total_contacts": len(interactions),
        "interactions": interactions,
    }


# ============================================================
# 8. Irregular Communication Patterns
# GET /api/cdr/patterns/{number}
# ============================================================

@router.get("/patterns/{number}")
async def get_cdr_irregular_patterns(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    )
):
    """
    Detect irregular or suspicious communication patterns
    for the target number.
    """

    summary = await get_cdr_summary(number)

    patterns = detect_irregular_patterns(
        summary.records,
        number,
    )

    return {
        "success": True,
        "target_number": number,
        "total_patterns": len(patterns),
        "patterns": patterns,
    }


# ============================================================
# 9. Communication Network
# GET /api/cdr/network/{number}
# ============================================================

@router.get("/network/{number}")
async def get_cdr_network(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$",
    )
):
    """
    Generate a communication network showing the target
    number and its contacts.
    """

    summary = await get_cdr_summary(number)

    network = generate_communication_network(
        summary.records,
        number,
    )

    return {
        "success": True,
        "target_number": number,
        "network": network,
    }