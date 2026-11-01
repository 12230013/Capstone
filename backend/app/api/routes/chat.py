from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database.connection import (
    conversations_collection,
    messages_collection,
)
from app.services.chat_service import ChatService
from app.services.llm_service import LLMService


router = APIRouter(prefix="/api", tags=["Chat"])


class ChatRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    folder_id: Optional[str] = None

chat_service = ChatService()
title_llm_service = LLMService()


def generate_conversation_title(query: str) -> str:
    """
    Generate a short conversation title using the local LLM.
    """

    cleaned = " ".join(query.strip().split())
    query_lower = cleaned.lower()

    # Give the LLM an explicit category hint so that identifiers such as
    # CIDs are not incorrectly interpreted as phone numbers.
    if any(
        word in query_lower
        for word in (
            "relationship",
            "relationships",
            "rship",
            "relative",
            "relatives",
            "family",
            "parent",
            "parents",
            "father",
            "mother",
            "sibling",
            "siblings",
            "brother",
            "sister",
            "degree",
        )
    ):
        category = "RELATIONSHIP"

    elif any(
        word in query_lower
        for word in (
            "cdr",
            "call",
            "calls",
            "phone",
            "communication",
            "incoming",
            "outgoing",
        )
    ):
        category = "CDR"

    elif any(
        word in query_lower
        for word in (
            "statement",
            "statements",
            "contradiction",
            "contradictions",
            "interview",
        )
    ):
        category = "STATEMENT"

    else:
        category = "GENERAL INVESTIGATION"

    prompt = f"""
Generate a short title for an anti-corruption investigation chatbot conversation.

Conversation category:
{category}

User message:
{cleaned}

Rules:
- Return only the title.
- Use 3 to 6 words.
- The title MUST match the conversation category above.
- Do not change a RELATIONSHIP request into a CDR request.
- Do not change a CDR request into a relationship request.
- Do not infer the type of an identifier from its digits alone.
- Describe the user's actual intent.
- Do not use quotation marks.
- Do not add a period.
- Do not write "Title:".
- Do not invent facts.

Examples:

RELATIONSHIP:
who are the parents of 10808000040
Parent Relationship Lookup

RELATIONSHIP:
give me the first degree rship for 10808000040
First-Degree Relationship Analysis

RELATIONSHIP:
show the complete family tree for 10808000040
Complete Family Tree Analysis

CDR:
analyze calls for 17123456
CDR Analysis for 17123456

STATEMENT:
find contradictions between these statements
Statement Contradiction Analysis

Now generate the title.
""".strip()

    try:
        title = title_llm_service.generate(prompt).strip()

        title = title.replace('"', "").replace("'", "")
        title = title.removeprefix("Title:").strip()
        title = title.rstrip(".").strip()

        if title:
            return title[:80]

    except Exception as exc:
        print(f"Conversation title generation error: {exc}")

    # Fallback
    if len(cleaned) <= 60:
        return cleaned

    return cleaned[:57].rstrip() + "..."


@router.post("/chat")
async def chat(request: ChatRequest):
    try:
        if conversations_collection is None or messages_collection is None:
            raise HTTPException(
                status_code=503,
                detail="Database connection is not available.",
            )

        query = request.query.strip()

        if not query:
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty.",
            )

        now = datetime.now(timezone.utc)

        # ---------------------------------------------------------
        # 1. Find an existing conversation or create a new one
        # ---------------------------------------------------------

        if request.conversation_id:
            if not ObjectId.is_valid(request.conversation_id):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid conversation ID.",
                )

            conversation = conversations_collection.find_one(
                {"_id": ObjectId(request.conversation_id)}
            )

            if conversation is None:
                raise HTTPException(
                    status_code=404,
                    detail="Conversation not found.",
                )

            conversation_id = str(conversation["_id"])

        else:
            if not request.user_id:
                raise HTTPException(
                    status_code=400,
                    detail="user_id is required when starting a new conversation.",
                )

            conversation = {
                "user_id": request.user_id,
                "title": generate_conversation_title(query),
                "folder_id": request.folder_id,
                "created_at": now,
                "updated_at": now,
            }

            result = conversations_collection.insert_one(conversation)
            conversation_id = str(result.inserted_id)

        # ---------------------------------------------------------
        # 2. Save the user's message
        # ---------------------------------------------------------

        messages_collection.insert_one({
            "conversation_id": conversation_id,
            "role": "user",
            "content": query,
            "sources": [],
            "created_at": now,
        })

        # ---------------------------------------------------------
        # 3. Load recent conversation context
        # ---------------------------------------------------------

        recent_messages = list(
            messages_collection.find(
                {"conversation_id": conversation_id}
            )
            .sort("created_at", -1)
            .limit(10)
        )

        recent_messages.reverse()

        conversation_context = {
            "current_query": query,
            "messages": [
                {
                    "role": message.get("role"),
                    "content": message.get("content", ""),
                }
                for message in recent_messages
            ]
        }

        # ---------------------------------------------------------
        # 4. Run the chatbot with conversation context
        # ---------------------------------------------------------

        result = await chat_service.query(
            query,
            context=conversation_context,
        )

        # ---------------------------------------------------------
        # 5. Extract assistant answer and sources
        # ---------------------------------------------------------

        response_data = result.get("response", {})

        if isinstance(response_data, dict):
            answer = response_data.get(
                "answer",
                "No response was generated.",
            )
            sources = response_data.get("sources", [])
        else:
            answer = str(response_data)
            sources = []

        # ---------------------------------------------------------
        # 6. Save the assistant's message
        # ---------------------------------------------------------

        assistant_time = datetime.now(timezone.utc)

        messages_collection.insert_one({
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": answer,
            "sources": sources,
            "created_at": assistant_time,
        })

        # Put the most recently used conversation at the top
        conversations_collection.update_one(
            {"_id": ObjectId(conversation_id)},
            {
                "$set": {
                    "updated_at": assistant_time,
                }
            },
        )

        # ---------------------------------------------------------
        # 7. Preserve the existing response structure
        # ---------------------------------------------------------

        result["conversation_id"] = conversation_id

        return result

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        print(f"Chat route error: {exc}")

        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing the chat request.",
        ) from exc