from fastapi import FastAPI, HTTPException, Path
import httpx

from app.services.cdr_service import CDRService
from app.services.rag_service import RAGService
from app.analytics.cdr_analytics import (
    analyze_communication_frequency,
    analyze_communication_direction,
    filter_records_by_date,
    analyze_period_statistics,
    generate_communication_timeline,
    analyze_interactions,
    detect_irregular_patterns,
    generate_communication_network
)
from datetime import date
from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel

class ChatRequest(BaseModel):
    query: str

app = FastAPI(
    title="ACC Investigation Chatbot API",
    description="Backend API for the ACC RAG-based chatbot",
    version="0.1.0"
)

cdr_service = CDRService()
rag_service = RAGService()
@app.get("/")
async def root():
    return {
        "message": "ACC Chatbot Backend is running"
    }

@app.post("/api/chat")
async def chat(request: ChatRequest):

    try:
        result = rag_service.query(
            query=request.query,
            limit=3
        )

        return {
            "success": True,
            "query": request.query,
            "answer": result["answer"],
            "sources": result["sources"]
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate answer: {str(exc)}"
        )


@app.get("/api/cdr/summary/{number}")
async def get_cdr_summary(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    )
):

    try:
        result = await cdr_service.get_summary(number)

        return result

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        )

@app.get("/api/cdr/frequency/{number}")
async def get_cdr_frequency(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    )
):
    try:
        # Get validated CDR records
        summary = await cdr_service.get_summary(number)

        # Analyze communication frequency
        frequency = analyze_communication_frequency(
            summary.records,
            number
        )

        return {
            "success": True,
            "target_number": number,
            "contacts": frequency
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        )

@app.get("/api/cdr/direction/{number}")
async def get_cdr_direction(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    )
):
    try:
        # Get validated CDR records
        summary = await cdr_service.get_summary(number)

        # Analyze incoming and outgoing communication
        direction = analyze_communication_direction(
            summary.records,
            number
        )

        return {
            "success": True,
            "target_number": number,
            "communication_direction": direction
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        )

@app.get("/api/cdr/records/{number}")
async def get_cdr_records_by_date(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    ),
    start_date: date = Query(...),
    end_date: date = Query(...)
):
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date"
        )

    try:
        # Retrieve validated CDR records
        summary = await cdr_service.get_summary(number)

        # Filter records within the requested date range
        filtered_records = filter_records_by_date(
            summary.records,
            start_date,
            end_date
        )

        return {
            "success": True,
            "target_number": number,
            "start_date": start_date,
            "end_date": end_date,
            "total_records": len(filtered_records),
            "records": filtered_records
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        )

@app.get("/api/cdr/statistics/{number}")
async def get_cdr_period_statistics(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    ),
    start_date: date = Query(...),
    end_date: date = Query(...)
):
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date"
        )

    try:
        # Retrieve validated CDR records
        summary = await cdr_service.get_summary(number)

        # Calculate statistics for the selected period
        result = analyze_period_statistics(
            summary.records,
            number,
            start_date,
            end_date
        )

        return {
            "success": True,
            "target_number": number,
            "period": {
                "start_date": result["start_date"],
                "end_date": result["end_date"]
            },
            "statistics": result["statistics"]
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        )

@app.get("/api/cdr/timeline/{number}")
async def get_cdr_timeline(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    ),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None)
):
    # Require both dates when a date range is supplied
    if (start_date is None) != (end_date is None):
        raise HTTPException(
            status_code=400,
            detail="Provide both start_date and end_date, or neither"
        )

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date"
        )

    try:
        # Retrieve validated CDR records
        summary = await cdr_service.get_summary(number)

        # Generate chronological timeline
        timeline = generate_communication_timeline(
            summary.records,
            number,
            start_date,
            end_date
        )

        return {
            "success": True,
            "target_number": number,
            "period": {
                "start_date": start_date,
                "end_date": end_date
            },
            "total_interactions": len(timeline),
            "timeline": timeline
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        )

@app.get("/api/cdr/interactions/{number}")
async def get_cdr_interactions(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    )
):
    try:
        # Retrieve validated CDR records
        summary = await cdr_service.get_summary(number)

        # Analyze communication with each contact
        interactions = analyze_interactions(
            summary.records,
            number
        )

        return {
            "success": True,
            "target_number": number,
            "total_contacts": len(interactions),
            "interactions": interactions
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        )

@app.get("/api/cdr/patterns/{number}")
async def get_cdr_irregular_patterns(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    )
):
    try:
        # Retrieve validated CDR records
        summary = await cdr_service.get_summary(number)

        # Detect irregular communication patterns
        patterns = detect_irregular_patterns(
            summary.records,
            number
        )

        return {
            "success": True,
            "target_number": number,
            "total_patterns": len(patterns),
            "patterns": patterns
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        )

@app.get("/api/cdr/network/{number}")
async def get_cdr_network(
    number: str = Path(
        ...,
        min_length=5,
        max_length=20,
        pattern=r"^[0-9]+$"
    )
):
    try:
        summary = await cdr_service.get_summary(number)

        network = generate_communication_network(
            summary.records,
            number
        )

        return {
            "success": True,
            "target_number": number,
            "network": network
        }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="CDR service timed out"
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"CDR service returned HTTP {exc.response.status_code}"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to CDR service"
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        )
