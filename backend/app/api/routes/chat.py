from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.chat_service import ChatService


router = APIRouter(
    prefix="/api",
    tags=["Chat"]
)


class ChatRequest(BaseModel):
    query: str


chat_service = ChatService()


@router.post("/chat")
async def chat(request: ChatRequest):
    try:
        return await chat_service.query(request.query)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )
