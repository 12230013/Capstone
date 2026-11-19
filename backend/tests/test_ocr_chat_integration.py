"""Focused mocked tests for OCR access through the existing chat service."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException

from app.api.routes import chat as chat_route
from app.services.chat_service import ChatService


class OCRChatIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = ChatService()
        self.service._rag_service = MagicMock()
        self.service._rag_service.query.return_value = {
            "answer": "Existing RAG answer.",
            "sources": [],
        }
        self.service._statement_service = MagicMock()
        self.service._statement_service.query_statement_evidence.return_value = {
            "success": True,
            "answer": "Existing statement answer.",
            "sources": [{"doc_id": "statement-1"}],
            "warnings": [],
            "disclaimer": "",
        }

    async def test_chat_route_passes_authenticated_session_owner_to_service(self):
        query = AsyncMock(
            return_value={
                "success": True,
                "response": {
                    "answer": "OCR answer.",
                    "sources": [{"filename": "owned.pdf", "page_number": 3}],
                },
            }
        )
        conversations = MagicMock()
        messages = MagicMock()
        activity = MagicMock()
        conversations.insert_one.return_value.inserted_id = ObjectId()
        activity.insert_one.return_value.inserted_id = ObjectId()
        request = chat_route.ChatRequest(
            query="Summarize owned.pdf",
            user_id=None,
        )

        with (
            patch.object(chat_route, "chat_service") as service,
            patch.object(chat_route, "conversations_collection", conversations),
            patch.object(chat_route, "messages_collection", messages),
            patch.object(chat_route, "activity_collection", activity),
            patch.object(chat_route, "folders_collection", MagicMock()),
        ):
            service.query = query
            await chat_route.chat(
                request,
                BackgroundTasks(),
                {"user_id": "session-owner"},
            )

        context = query.call_args.kwargs["context"]
        self.assertEqual(context["owner_user_id"], "session-owner")

    async def test_chat_route_rejects_client_owner_override(self):
        with self.assertRaises(HTTPException) as raised:
            await chat_route.chat(
                chat_route.ChatRequest(
                    query="Summarize owned.pdf",
                    user_id="attacker-supplied-id",
                ),
                BackgroundTasks(),
                {"user_id": "session-owner"},
            )

        self.assertEqual(raised.exception.status_code, 403)

    async def test_owned_ocr_document_uses_session_owner_and_preserves_citations(self):
        ocr_response = {
            "answer": "The transfer appears on [owned.pdf, page 3].",
            "sources": [{"filename": "owned.pdf", "page_number": 3}],
            "warnings": [],
            "disclaimer": "OCR evidence only.",
        }
        with patch(
            "app.ocr.chat_retrieval.ocr_chat_retrieval.retrieve",
            return_value=ocr_response,
        ) as retrieve:
            result = await self.service.query(
                "Summarize owned.pdf",
                context={
                    "owner_user_id": "session-owner",
                    "user_id": "attacker-supplied-id",
                },
            )

        self.assertEqual(result["success"], True)
        self.assertEqual(result["response"], ocr_response)
        retrieve.assert_called_once_with(
            "Summarize owned.pdf",
            "owned.pdf",
            "session-owner",
        )
        self.service._rag_service.query.assert_not_called()
        self.service._statement_service.query_statement_evidence.assert_not_called()

    async def test_unavailable_owned_ocr_document_preserves_normal_rag_fallback(self):
        with patch(
            "app.ocr.chat_retrieval.ocr_chat_retrieval.retrieve",
            return_value=None,
        ):
            result = await self.service.query(
                "Summarize unavailable.pdf",
                context={"owner_user_id": "session-owner"},
            )

        self.assertEqual(result["success"], True)
        self.assertEqual(result["response"]["answer"], "Existing RAG answer.")
        self.service._rag_service.query.assert_called_once()

    async def test_existing_statement_chat_does_not_enter_ocr_path(self):
        with patch(
            "app.ocr.chat_retrieval.ocr_chat_retrieval.retrieve",
        ) as retrieve:
            result = await self.service.query(
                "Summarize the statement evidence",
                context={"owner_user_id": "session-owner"},
            )

        self.assertEqual(result["response"]["answer"], "Existing statement answer.")
        retrieve.assert_not_called()
        self.service._statement_service.query_statement_evidence.assert_called_once_with(
            query="Summarize the statement evidence"
        )
        self.service._rag_service.query.assert_not_called()

    async def test_existing_normal_rag_chat_does_not_enter_ocr_path(self):
        with patch(
            "app.ocr.chat_retrieval.ocr_chat_retrieval.retrieve",
        ) as retrieve:
            result = await self.service.query(
                "What information is available?",
                context={"owner_user_id": "session-owner"},
            )

        self.assertEqual(result["response"]["answer"], "Existing RAG answer.")
        retrieve.assert_not_called()
        self.service._rag_service.query.assert_called_once()
        self.service._statement_service.query_statement_evidence.assert_not_called()


if __name__ == "__main__":
    unittest.main()
