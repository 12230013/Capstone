import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.services.chat_service import ChatService
from app.services.unified_evidence import answer_from_unified_evidence


def _ocr_chunk():
    return {
        "text": "[p2-c1] OCR evidence",
        "metadata": {
            "metadata": {
                "document_id": "ocr-doc-1",
                "filename": "owned.pdf",
                "page_number": 2,
                "chunk_id": "p2-c1",
            }
        },
    }


def _model_answer():
    return json.dumps({
        "has_information": True,
        "claims": [{
            "statement": "The statement and OCR record support the same event.",
            "evidence": [
                {"evidence_id": "statement:stmt_01-s1", "quote": "Statement evidence"},
                {"evidence_id": "ocr:ocr-doc-1:p2-c1", "quote": "OCR evidence"},
            ],
        }],
        "missing_information": [],
    })


def _statement_service(evidence):
    return SimpleNamespace(
        retrieve_statement_evidence=Mock(return_value={
            "success": True,
            "evidence": evidence,
            "warnings": [],
        })
    )


@pytest.mark.asyncio
async def test_mixed_query_combines_statement_and_owned_ocr_citations():
    service = ChatService()
    service._statement_service = SimpleNamespace(
        retrieve_statement_evidence=Mock(return_value={
            "success": True,
            "evidence": [{
                "statement_id": "stmt_01",
                "text": "[stmt_01-s1] Statement evidence",
            }],
            "warnings": [],
        })
    )
    service._llm_service = SimpleNamespace(generate=Mock(return_value=_model_answer()))

    with patch("app.ocr.chat_retrieval.ocr_chat_retrieval") as ocr_service:
        ocr_service.retrieve_evidence.return_value = [_ocr_chunk()]
        result = await service.query(
            "Compare the statement evidence with owned.pdf",
            context={"owner_user_id": "owner-a"},
        )

    ocr_service.retrieve_evidence.assert_called_once_with(
        "Compare the statement evidence with owned.pdf",
        "owned.pdf",
        "owner-a",
    )
    assert "[stmt_01-s1]" in result["response"]["answer"]
    assert "[owned.pdf, page 2]" in result["response"]["answer"]
    assert {source["source_type"] for source in result["response"]["sources"]} == {
        "statement", "ocr_document"
    }


@pytest.mark.asyncio
async def test_unowned_ocr_document_is_excluded_from_mixed_evidence():
    service = ChatService()
    service._statement_service = SimpleNamespace(
        retrieve_statement_evidence=Mock(return_value={
            "success": True,
            "evidence": [{
                "statement_id": "stmt_01",
                "text": "[stmt_01-s1] Statement evidence",
            }],
            "warnings": [],
        })
    )
    service._llm_service = SimpleNamespace(generate=Mock(return_value=json.dumps({
        "has_information": True,
        "claims": [{
            "statement": "Only the statement is available.",
            "evidence": [{
                "evidence_id": "statement:stmt_01-s1",
                "quote": "Statement evidence",
            }],
        }],
        "missing_information": [],
    })))

    with patch("app.ocr.chat_retrieval.ocr_chat_retrieval") as ocr_service:
        ocr_service.retrieve_evidence.return_value = None
        result = await service.query(
            "Compare the statement evidence with other.pdf",
            context={"owner_user_id": "owner-a"},
        )

    assert "[other.pdf, page" not in result["response"]["answer"]
    assert result["response"]["sources"][0]["source_type"] == "statement"
    assert result["response"]["warnings"]


def test_unified_grounding_rejects_unsupported_citations():
    result = answer_from_unified_evidence(
        "Question",
        [{
            "evidence_id": "ocr:doc-1:p1-c1",
            "citation": "owned.pdf, page 1",
            "source_type": "ocr_document",
            "document_id": "doc-1",
            "filename": "owned.pdf",
            "page_number": 1,
            "chunk_id": "p1-c1",
            "text": "OCR evidence",
        }],
        lambda prompt, response_format: json.dumps({
            "has_information": True,
            "claims": [{
                "statement": "Unsupported.",
                "evidence": [{
                    "evidence_id": "ocr:doc-1:p1-c1",
                    "quote": "Different evidence",
                }],
            }],
            "missing_information": [],
        }),
    )
    assert result["has_information"] is False
    assert result["sources"] == []


@pytest.mark.asyncio
async def test_empty_statement_evidence_can_still_answer_from_ocr():
    service = ChatService()
    service._statement_service = _statement_service([])
    service._llm_service = SimpleNamespace(generate=Mock(return_value=json.dumps({
        "has_information": True,
        "claims": [{
            "statement": "The OCR page contains the evidence.",
            "evidence": [{
                "evidence_id": "ocr:ocr-doc-1:p2-c1",
                "quote": "OCR evidence",
            }],
        }],
        "missing_information": [],
    })))

    with patch("app.ocr.chat_retrieval.ocr_chat_retrieval") as ocr_service:
        ocr_service.retrieve_evidence.return_value = [_ocr_chunk()]
        result = await service.query(
            "Compare the statement evidence with owned.pdf",
            context={"owner_user_id": "owner-a"},
        )

    assert "[owned.pdf, page 2]" in result["response"]["answer"]
    assert result["response"]["sources"][0]["source_type"] == "ocr_document"


@pytest.mark.asyncio
async def test_empty_statement_and_ocr_evidence_return_without_model_call():
    service = ChatService()
    service._statement_service = _statement_service([])
    generate = Mock()
    service._llm_service = SimpleNamespace(generate=generate)

    with patch("app.ocr.chat_retrieval.ocr_chat_retrieval") as ocr_service:
        ocr_service.retrieve_evidence.return_value = None
        result = await service.query(
            "Compare the statement evidence with missing.pdf",
            context={"owner_user_id": "owner-a"},
        )

    assert result["response"]["answer"] == (
        "I don't have information for this question in the available records."
    )
    assert result["response"]["sources"] == []
    generate.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_retrieval_makes_exactly_one_unified_model_call():
    service = ChatService()
    service._statement_service = _statement_service([{
        "statement_id": "stmt_01",
        "text": "[stmt_01-s1] Statement evidence",
    }])
    generate = Mock(return_value=_model_answer())
    service._llm_service = SimpleNamespace(generate=generate)

    with patch("app.ocr.chat_retrieval.ocr_chat_retrieval") as ocr_service:
        ocr_service.retrieve_evidence.return_value = [_ocr_chunk()]
        await service.query(
            "Compare the statement evidence with owned.pdf",
            context={"owner_user_id": "owner-a"},
        )

    generate.assert_called_once()
    ocr_service.retrieve_evidence.assert_called_once()
