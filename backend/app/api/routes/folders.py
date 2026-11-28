import re
from app.utils.sessions import require_session, check_user_id
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database.connection import (
    folders_collection,
    conversations_collection,
)

router = APIRouter(
    prefix="/api/folders",
    tags=["Folders"],
)


from app.services.cims_service import authorize_conversation_scope


class FolderCreate(BaseModel):
    user_id: str | None = None
    name: str


class AddConversationToFolder(BaseModel):
    conversation_id: str


def serialize_folder(folder: dict) -> dict:
    return {
        "id": str(folder["_id"]),
        "user_id": folder["user_id"],
        "name": folder["name"],
        "created_at": folder.get("created_at"),
    }


@router.post("")
def create_folder(request: FolderCreate, session: dict = Depends(require_session)):
    user_id = check_user_id(request.user_id, session)
    if folders_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    name = request.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Folder name is required.",
        )

    existing_folder = folders_collection.find_one(
        {
            "user_id": user_id,
            "name": {
                "$regex": f"^{re.escape(name)}$",
                "$options": "i",
            },
        }
    )

    if existing_folder is not None:
        raise HTTPException(
            status_code=409,
            detail="A folder with this name already exists.",
        )

    folder = {
        "user_id": user_id,
        "name": name,
        "created_at": datetime.now(timezone.utc),
    }

    result = folders_collection.insert_one(folder)

    created_folder = folders_collection.find_one(
        {"_id": result.inserted_id}
    )

    return {
        "success": True,
        "folder": serialize_folder(created_folder),
    }


@router.get("")
def list_folders(user_id: str = None, session: dict = Depends(require_session)):
    user_id = check_user_id(user_id, session)
    if folders_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    folders = folders_collection.find(
        {"user_id": user_id}
    ).sort("created_at", 1)

    return {
        "success": True,
        "folders": [
            serialize_folder(folder)
            for folder in folders
        ],
    }


@router.post("/{folder_id}/conversations")
def add_conversation_to_folder(
    folder_id: str,
    request: AddConversationToFolder,
    session: dict = Depends(require_session),
):
    if folders_collection is None or conversations_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    if not ObjectId.is_valid(folder_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid folder ID.",
        )

    if not ObjectId.is_valid(request.conversation_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID.",
        )

    folder = folders_collection.find_one(
        {"_id": ObjectId(folder_id), "user_id": session["user_id"]}
    )

    if folder is None:
        raise HTTPException(
            status_code=404,
            detail="Folder not found.",
        )

    conversation = conversations_collection.find_one(
        {"_id": ObjectId(request.conversation_id), "user_id": session["user_id"]}
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    authorize_conversation_scope(session, conversation)

    # Prevent assigning another user's conversation to this folder.
    if conversation.get("user_id") != folder.get("user_id"):
        raise HTTPException(
            status_code=403,
            detail="Conversation and folder belong to different users.",
        )

    conversations_collection.update_one(
        {"_id": ObjectId(request.conversation_id), "user_id": session["user_id"]},
        {
            "$set": {
                "folder_id": folder_id,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    return {
        "success": True,
        "message": "Conversation added to folder.",
        "conversation_id": request.conversation_id,
        "folder_id": folder_id,
    }


@router.delete("/{folder_id}")
def delete_folder(folder_id: str, session: dict = Depends(require_session)):
    if folders_collection is None or conversations_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available.",
        )

    if not ObjectId.is_valid(folder_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid folder ID.",
        )

    folder = folders_collection.find_one(
        {"_id": ObjectId(folder_id), "user_id": session["user_id"]}
    )

    if folder is None:
        raise HTTPException(
            status_code=404,
            detail="Folder not found.",
        )

    # Keep conversations, but remove them from the deleted folder.
    conversations_collection.update_many(
        {"folder_id": folder_id, "user_id": session["user_id"]},
        {
            "$unset": {
                "folder_id": "",
            }
        },
    )

    folders_collection.delete_one(
        {"_id": ObjectId(folder_id), "user_id": session["user_id"]}
    )

    return {
        "success": True,
        "message": "Folder deleted successfully.",
        "folder_id": folder_id,
    }
