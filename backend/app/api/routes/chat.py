from datetime import datetime, timezone
import hashlib
import re
from typing import Literal, Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from pymongo.errors import ConnectionFailure
import requests

from app.database.connection import activity_collection, conversations_collection, messages_collection, folders_collection
from app.services.chat_service import ChatService
from app.services.cims_service import authorize_conversation_scope, infer_case_mode, resolve_case_reference
from app.services.cims_documents import conversation_message_scope
from app.services.llm_service import LLMService
from app.services.message_history import successful_exchanges
from app.services.presentation_access import HAA_SCOPE, TOOL_SCOPE, is_haa_reference, presentation_request, presentation_scope
from app.utils.sessions import require_session, check_user_id

router = APIRouter(prefix="/api", tags=["Chat"])


class ChatRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    folder_id: Optional[str] = None
    request_id: Optional[str] = None
    case_id: Optional[str] = None
    case_mode: Literal["metadata", "documents", "cdr", "relationships"] | None = None
    case_subject: str | None = None


chat_service = ChatService()


def case_conversation_title(case_id, mode, question):
    from app.services.cims_documents import is_case_overview

    if case_id == TOOL_SCOPE:
        return {"cdr": "Call records", "relationships": "Relationship mapping"}[mode]
    case_label = "HAA case" if case_id == HAA_SCOPE else f"Case {case_id}"
    if is_case_overview(question) or re.search(r"\btell me about (?:the )?haa case\b", question, re.I):
        topic = "Overview"
    elif re.search(r"\b(?:timeline|chronology|sequence of events)\b", question, re.I):
        topic = "Timeline"
    elif re.search(r"\b(?:report|document|file)\b", question, re.I):
        topic = re.sub(r"^(?:please\s+)?(?:tell me about|summarize|explain)\s+(?:the\s+)?", "", question, flags=re.I)
    elif re.search(r"\b(?:people|involved|witnesses|suspects)\b", question, re.I):
        topic = "People involved"
    else:
        topic = question
    topic = " ".join(topic.split()).strip(" ?.!") or "Overview"
    return f"{case_label} · {topic[0].upper()}{topic[1:]}"[:80].rstrip()


def generate_conversation_title(conversation_id: str, query: str):
    """Generate the title after the answer has been sent to the browser."""
    title_filter = {"_id": ObjectId(conversation_id), "title_seed": query, "title_status": "pending"}
    try:
        prompt = (
            "Write a descriptive conversation title of 3 to 6 words for this question. "
            "Preserve its topic and identifiers. Return only the title without quotation marks.\n"
            f"Question: {query[:1000]}\nTitle:"
        )
        title = LLMService().generate(prompt, max_tokens=24).split("\n", 1)[0].strip()
        title = title.removeprefix("Title:").strip().strip('"').rstrip(".")
        if not title:
            raise ValueError("Empty generated title")
        conversations_collection.update_one(title_filter, {"$set": {"title": title[:80], "title_status": "ready"}})
    except Exception as exc:
        print(f"Conversation title generation failed: {exc}")
        conversations_collection.update_one(title_filter, {"$set": {"title_status": "fallback"}})


@router.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks, session: dict = Depends(require_session)):
    user_id = check_user_id(request.user_id, session)
    try:
        if conversations_collection is None or messages_collection is None or activity_collection is None:
            raise HTTPException(503, "Database connection is not available.")

        query = request.query.strip()
        if not query:
            raise HTTPException(400, "Query cannot be empty.")

        now = datetime.now(timezone.utc)
        conversation_id = request.conversation_id
        case_id = request.case_id
        case_mode = request.case_mode or "metadata"
        case_subject = request.case_subject
        demo = presentation_scope(session)
        inferred_case = None
        if request.case_id is None and not (demo is not None and is_haa_reference(query)):
            inferred_case = resolve_case_reference(session, query)
        demo_request = presentation_request(session, query, inferred_case) if demo is not None else None
        if demo_request is not None:
            inferred_case = demo_request[0]
        recent_messages = []
        history_scope = {}
        existing_conversation = None
        if conversation_id:
            if not ObjectId.is_valid(conversation_id):
                raise HTTPException(400, "Invalid conversation ID.")
            conversation = conversations_collection.find_one({"_id": ObjectId(conversation_id), "user_id": user_id})
            if conversation is None:
                raise HTTPException(404, "Conversation not found.")
            existing_conversation = conversation
            if demo_request is not None and demo_request != (
                conversation.get("case_id"), conversation.get("case_mode"), conversation.get("case_subject")
            ):
                conversation_id = None
            elif inferred_case is not None and not conversation.get("case_id"):
                conversation_id = None
            elif inferred_case is not None and inferred_case != conversation.get("case_id"):
                raise HTTPException(403, "Start a new conversation to ask about a different case.")
        if conversation_id:
            case_id = existing_conversation.get("case_id")
            if request.case_id is not None and request.case_id != case_id:
                raise HTTPException(403, "Case access denied.")
            case_mode = conversation.get("case_mode", "metadata")
            if request.case_mode is not None and request.case_mode != case_mode:
                raise HTTPException(403, "Case access denied.")
            case_subject = conversation.get("case_subject")
            if request.case_subject is not None and request.case_subject != case_subject:
                raise HTTPException(403, "Case access denied.")
            authorize_conversation_scope(session, conversation)
            history_scope = conversation_message_scope(session, conversation)
            history = messages_collection.find({
                "conversation_id": conversation_id, **history_scope,
            }).sort("created_at", 1)
            recent_messages = successful_exchanges(history)[-10:]
        else:
            if demo_request is not None:
                case_id, case_mode, case_subject = demo_request
            elif inferred_case is not None:
                case_id = inferred_case
                case_mode, case_subject = infer_case_mode(query)
            if demo is not None and case_id is None:
                case_id = demo["case_id"]
                case_mode, case_subject = infer_case_mode(query)
                if case_id == HAA_SCOPE:
                    case_mode = "metadata"
            if case_id is not None:
                authorize_conversation_scope(session, {
                    "case_id": case_id, "case_mode": case_mode, "case_subject": case_subject,
                })
            if request.folder_id:
                if not ObjectId.is_valid(request.folder_id):
                    raise HTTPException(400, "Invalid folder ID.")
                folder = folders_collection.find_one({"_id": ObjectId(request.folder_id), "user_id": user_id})
                if folder is None:
                    raise HTTPException(404, "Folder not found.")
            if not user_id:
                raise HTTPException(400, "user_id is required when starting a new conversation.")
            cleaned = " ".join(query.split())
            conversation = {
                "user_id": user_id,
                "title": cleaned if len(cleaned) <= 60 else cleaned[:57].rstrip() + "...",
                "folder_id": request.folder_id,
                "created_at": now,
                "updated_at": now,
            }

        if case_id is not None:
            conversation["case_id"] = case_id
            conversation["case_mode"] = case_mode
            if case_mode in {"cdr", "relationships"}:
                conversation["case_subject"] = case_subject
            if not conversation_id:
                conversation["title"] = case_conversation_title(case_id, case_mode, query)
                conversation["title_status"] = "ready"

        if request.request_id:
            if not conversation_id:
                history_scope = conversation_message_scope(session, conversation)
            replay_key = {"request_id": request.request_id, "user_id": user_id, "role": "assistant"}
            replay_scope = {**replay_key, "case_id": case_id, **history_scope}
            if case_id is not None:
                replay_scope["case_mode"] = case_mode
                replay_scope["case_subject"] = case_subject
            if conversation_id:
                replay_scope["conversation_id"] = conversation_id
            previous = messages_collection.find_one(replay_scope)
            if previous and previous.get("result"):
                return previous["result"]
            if case_id is not None and messages_collection.find_one(replay_key, {"_id": 1}):
                raise HTTPException(403, "Case access denied.")

        activity_id = activity_collection.insert_one({
            "user_id": conversation["user_id"], "type": "query", "query": query if case_id is None else None,
            "case_mode": case_mode,
            "case_subject": case_subject,
            "case_id": case_id,
            "sources": [], "conversation_id": conversation_id, "created_at": now,
        }).inserted_id

        context_messages = [{"role": message["role"], "content": message.get("content", ""),
                             "sources": message.get("sources", [])} for message in recent_messages]
        context_messages.append({"role": "user", "content": query})
        result = await chat_service.query(
            query,
            context={
                "current_query": query,
                "messages": context_messages,
                "owner_user_id": session["user_id"],
                "enforce_external_case_scope": True,
                **({
                    "case_id": case_id, "case_mode": case_mode,
                    "case_subject": case_subject, "session": session,
                } if case_id is not None else {}),
            },
        )
        if result.get("success") is False:
            raise HTTPException(502, result.get("message") or "The query could not be completed. Please try again.")

        response_data = result.get("response", {})
        if isinstance(response_data, dict):
            answer = response_data.get("answer", "No response was generated.")
            sources = response_data.get("sources", [])
            visualization = response_data.get("visualization") or result.get("visualization")
        else:
            answer, sources, visualization = str(response_data), [], result.get("visualization")

        if any(error in str(answer).lower() for error in (
            "collection not found", "unsupported relationship degree", "invalid phone number",
        )):
            raise HTTPException(502, str(answer))

        # Persist only completed exchanges. A failed first request creates no empty conversation.
        created_conversation = not conversation_id
        if created_conversation:
            conversation_id = str(conversations_collection.insert_one(conversation).inserted_id)
        result["conversation_id"] = conversation_id
        assistant_time = datetime.now(timezone.utc)
        exchange_id = str(ObjectId())
        common = {
            "conversation_id": conversation_id, "exchange_id": exchange_id,
            "user_id": conversation["user_id"], "request_id": request.request_id, "case_id": case_id, "case_mode": case_mode,
            "case_subject": case_subject,
        }
        user_message = {**common, "role": "user", "content": query, "sources": [], "created_at": now}
        assistant_message = {
            **common, "role": "assistant", "content": answer, "sources": sources,
            "visualization": visualization, "created_at": assistant_time, "result": result,
        }
        if case_id is not None:
            assistant_message["source_versions"] = sorted({
                source["version"] for source in sources
                if source.get("source_type") == "cims_document" and source.get("version")
            })
        if request.request_id:
            request_key = hashlib.sha256(
                f"{conversation['user_id']}:{request.request_id}".encode()
            ).hexdigest()
            user_message["_id"] = request_key + ":user"
            assistant_message["_id"] = request_key + ":assistant"
        try:
            messages_collection.insert_many([user_message, assistant_message])
        except Exception:
            messages_collection.delete_many({"exchange_id": exchange_id})
            if created_conversation:
                conversations_collection.delete_one({"_id": ObjectId(conversation_id)})
            raise

        updates = {"updated_at": assistant_time}
        needs_title = case_id is None and conversation.get("title_status") not in ("ready", "pending")
        title_seed = next((message["content"] for message in recent_messages if message["role"] == "user"), query)
        if case_id is not None and conversation.get("title") == "Case conversation":
            updates.update({"title": case_conversation_title(case_id, case_mode, title_seed), "title_status": "ready"})
        if needs_title:
            updates.update({"title_status": "pending", "title_seed": title_seed})
        conversations_collection.update_one({"_id": ObjectId(conversation_id)}, {"$set": updates})
        activity_collection.update_one({"_id": activity_id}, {"$set": {"sources": sources if case_id is None else [], "conversation_id": conversation_id}})
        if needs_title:
            background_tasks.add_task(generate_conversation_title, conversation_id, title_seed)
        return result

    except HTTPException:
        raise

    except ConnectionFailure as exc:
        raise HTTPException(
            503,
            "The database is unavailable. Start MongoDB and try again.",
        ) from exc

    except (TimeoutError, requests.Timeout) as exc:
        raise HTTPException(504, "Document analysis timed out. The local model may be busy or still loading. Please try again with a more specific question.") from exc

    except requests.ConnectionError as exc:
        raise HTTPException(503, "The local AI model is unavailable. Check that Ollama is running.") from exc

    except requests.HTTPError as exc:
        body = exc.response.text.lower() if exc.response is not None else ""
        if "allocate" in body and "buffer" in body:
            raise HTTPException(
                503,
                "Ollama does not have enough memory to load the AI model. Close unused applications or restart the computer, then try again.",
            ) from exc
        raise HTTPException(502, "The local AI model failed to generate a response. Check the Ollama logs.") from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        print(f"Chat route error: {type(exc).__name__}")

        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing the chat request.",
        ) from exc
