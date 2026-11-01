from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database.connection import (
    conversations_collection,
    messages_collection,
)

router = APIRouter(
    prefix="/api/conversations",
    tags=["Conversations"],
)


class ConversationCreate(BaseModel):
    user_id: str
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
        "created_at": message.get("created_at"),
    }

@router.post("")
def create_conversation(request: ConversationCreate):
    if conversations_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    now = datetime.now(timezone.utc)

    conversation = {
        "user_id": request.user_id,
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
def list_conversations(user_id: str):
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
        ],
    }


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str):
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
        {"_id": ObjectId(conversation_id)}
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return {
        "success": True,
        "conversation": serialize_conversation(conversation),
    }

@router.get("/{conversation_id}/messages")
def get_conversation_messages(conversation_id: str):
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
        {"_id": ObjectId(conversation_id)}
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    messages = messages_collection.find(
        {"conversation_id": conversation_id}
    ).sort("created_at", 1)

    return {
        "success": True,
        "conversation": serialize_conversation(conversation),
        "messages": [
            serialize_message(message)
            for message in messages
        ],
    }

@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str):
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
        {"_id": ObjectId(conversation_id)}
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    # Delete all messages belonging to this conversation first
    message_result = messages_collection.delete_many(
        {"conversation_id": conversation_id}
    )

    # Delete the conversation itself
    conversations_collection.delete_one(
        {"_id": ObjectId(conversation_id)}
    )

    return {
        "success": True,
        "message": "Conversation deleted successfully.",
        "conversation_id": conversation_id,
        "deleted_messages": message_result.deleted_count,
    }