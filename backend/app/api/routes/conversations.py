from app.utils.sessions import require_session, check_user_id
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.services.message_history import successful_exchanges

from app.database.connection import (
    conversations_collection,
    messages_collection,
)

router = APIRouter(
    prefix="/api/conversations",
    tags=["Conversations"],
)


from app.services.cims_service import authorize_conversation_scope, case_visible
from app.services.cims_documents import conversation_message_scope


class ConversationCreate(BaseModel):
    user_id: str | None = None
    title: str = "New Conversation"

def serialize_datetime(value):
    if value is None:
        return None

    # PyMongo may return UTC datetimes without tzinfo.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def serialize_conversation(conversation: dict) -> dict:
    return {
        "id": str(conversation["_id"]),
        "user_id": conversation["user_id"],
        "title": conversation.get("title", "New Conversation"),
        "title_status": conversation.get("title_status"),
        "case_id": conversation.get("case_id"),
        "case_mode": conversation.get("case_mode"),
        "folder_id": conversation.get("folder_id"),
        "created_at": serialize_datetime(conversation.get("created_at")),
        "updated_at": serialize_datetime(conversation.get("updated_at")),
    }

def serialize_message(message: dict) -> dict:
    return {
        "id": str(message["_id"]),
        "conversation_id": message["conversation_id"],
        "role": message["role"],
        "content": message["content"],
        "sources": message.get("sources", []),
        "visualization": message.get("visualization"),
        "created_at": message.get("created_at"),
    }

@router.post("")
def create_conversation(request: ConversationCreate, session: dict = Depends(require_session)):
    user_id = check_user_id(request.user_id, session)
    if conversations_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    now = datetime.now(timezone.utc)

    conversation = {
        "user_id": user_id,
        "title": request.title.strip() or "New Conversation",
        "created_at": now,
        "updated_at": now,
    }

    result = conversations_collection.insert_one(conversation)

    created_conversation = conversations_collection.find_one(
        {"_id": result.inserted_id}
    )

    return {
        "success": True,
        "conversation": serialize_conversation(created_conversation),
    }


@router.get("")
def list_conversations(user_id: str = None, session: dict = Depends(require_session)):
    user_id = check_user_id(user_id, session)
    if conversations_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    conversations = conversations_collection.find(
        {"user_id": user_id}
    ).sort("updated_at", -1)

    return {
        "success": True,
        "conversations": [
            serialize_conversation(conversation)
            for conversation in conversations
            if case_visible(session, conversation)
        ],
    }


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, session: dict = Depends(require_session)):
    if conversations_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    if not ObjectId.is_valid(conversation_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID.",
        )

    conversation = conversations_collection.find_one(
        {"_id": ObjectId(conversation_id), "user_id": session["user_id"]}
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    authorize_conversation_scope(session, conversation)

    return {
        "success": True,
        "conversation": serialize_conversation(conversation),
    }

@router.get("/{conversation_id}/messages")
def get_conversation_messages(conversation_id: str, session: dict = Depends(require_session)):
    if conversations_collection is None or messages_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    if not ObjectId.is_valid(conversation_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID.",
        )

    conversation = conversations_collection.find_one(
        {"_id": ObjectId(conversation_id), "user_id": session["user_id"]}
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    authorize_conversation_scope(session, conversation)

    messages = messages_collection.find(
        {"conversation_id": conversation_id, **conversation_message_scope(session, conversation)}
    ).sort("created_at", 1)

    return {
        "success": True,
        "conversation": serialize_conversation(conversation),
        "messages": [
            serialize_message(message)
            for message in successful_exchanges(messages)
        ],
    }

@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, session: dict = Depends(require_session)):
    if conversations_collection is None or messages_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    if not ObjectId.is_valid(conversation_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID.",
        )

    conversation = conversations_collection.find_one(
        {"_id": ObjectId(conversation_id), "user_id": session["user_id"]}
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    authorize_conversation_scope(session, conversation)

    # Delete all messages belonging to this conversation first
    message_result = messages_collection.delete_many(
        {"conversation_id": conversation_id}
    )

    # Delete the conversation itself
    conversations_collection.delete_one(
        {"_id": ObjectId(conversation_id), "user_id": session["user_id"]}
    )

    return {
        "success": True,
        "message": "Conversation deleted successfully.",
        "conversation_id": conversation_id,
        "deleted_messages": message_result.deleted_count,
    }
