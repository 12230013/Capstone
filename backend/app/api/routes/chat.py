from fastapi import APIRouter
from pydantic import BaseModel

from app.services.rag_service import RAGService


router = APIRouter(
    prefix="/api",
    tags=["Chat"]
)


class ChatRequest(BaseModel):
    query: str


rag_service = RAGService()


@router.post("/chat")
async def chat(request: ChatRequest):

    response = rag_service.query(
        request.query
    )

    return {
        "success": True,
        "response": response
    }

