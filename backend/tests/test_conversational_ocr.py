import json
from unittest.mock import Mock
from unittest.mock import patch
import pytest

from app.services.chat_service import ChatService
from app.services.unified_evidence import answer_from_unified_evidence, compact_evidence


def test_followup_keeps_subject_and_marks_previous_answer_as_reference_only():
    query = ChatService._conversational_document_query("What is its case number?", {"messages": [
        {"role": "user", "content": "Summarize the Haa investigation"},
        {"role": "assistant", "content": "UNTRUSTED FACT", "sources": [{"filename": "owned.pdf"}]},
        {"role": "user", "content": "What is its case number?"},
    ]})
    assert "Haa" in query and "owned.pdf" in query
    assert "resolve references only; verify again against retrieved evidence" in query


def record(text, key="ocr:doc:p1-c1"):
    return {"evidence_id": key, "citation": "owned.pdf, page 1", "source_type": "ocr_document",
            "document_id": "doc", "filename": "owned.pdf", "page_number": 1, "text": text}


def test_exact_case_number_returns_verified_page_citation_without_generation():
    generate = Mock()
    result = answer_from_unified_evidence("What is the case number of Haa case?", [
        record("Haa investigation. Case No: | 19/25-26")], generate)
    assert "19/25-26" in result["answer"] and "[owned.pdf, page 1]" in result["answer"]
    assert result["sources"][0]["page_number"] == 1
    assert result["sources"][0]["quotes"] == ["19/25-26"]
    generate.assert_not_called()


def test_conflicting_case_identifiers_are_not_chosen_arbitrarily():
    generate = Mock(return_value=json.dumps({"has_information": False, "claims": [], "missing_information": ["Which case?"]}))
    result = answer_from_unified_evidence("What is the case number?", [
        record("Case No: 19/25-26"), record("Case No: 20/25-26", "ocr:other:p1-c1")], generate)
    generate.assert_called_once()
    assert not result["has_information"]


def test_large_table_context_keeps_relevant_window_within_budget():
    text = "Unrelated table row\n" * 3000 + "Case No: | 19/25-26" + "Other rows\n" * 3000
    selected = compact_evidence("What is the case number?", [record(text)])
    assert "19/25-26" in selected[0]["text"]
    assert sum(len(x["text"].encode()) for x in selected) < 8000


def test_known_statement_label_resolves_only_with_a_matching_source_quote():
    evidence=[{"evidence_id":"statement:stmt_01-s4", "citation":"stmt_01-s4", "sentence_id":"stmt_01-s4",
               "statement_id":"stmt_01", "source_type":"statement", "text":"I owned my sawmill."}]
    def answer(quote):
        return lambda *args,**kwargs: json.dumps({"has_information":True,"claims":[{
            "statement":"The witness owned a sawmill.","evidence":[{"evidence_id":"stmt_01-s4","quote":quote}]}],"missing_information":[]})
    result=answer_from_unified_evidence("What business?", evidence, answer("I owned my sawmill."))
    assert "[stmt_01-s4]" in result["answer"]
    assert not answer_from_unified_evidence("What business?", evidence, answer("I own a casino."))["has_information"]


@pytest.mark.asyncio
async def test_greeting_after_case_discussion_never_retrieves_or_generates_facts():
    service=ChatService()
    service._llm_service=Mock()
    with patch('app.ocr.chat_retrieval.ocr_chat_retrieval') as retrieval:
        result=await service.query('hi', {'owner_user_id':'owner', 'messages':[{'role':'user','content':'Tell me about Kinga Norbu Haa case'}]})
        retrieval.retrieve_all_evidence.assert_not_called()
        retrieval.retrieve.assert_not_called()
    assert 'Hello' in result['response']['answer']
    assert result['response']['sources']==[]
    service._llm_service.generate.assert_not_called()


@pytest.mark.asyncio
async def test_statements_in_specific_upload_does_not_search_unrelated_statements():
    service=ChatService()
    service._statement_service=Mock()
    with patch('app.ocr.chat_retrieval.ocr_chat_retrieval') as retrieval:
        retrieval.retrieve.return_value={'answer':'Uploaded evidence','sources':[]}
        result=await service.query('what statements are in document1.pdf', {'owner_user_id':'owner'})
        retrieval.retrieve.assert_called_once_with('what statements are in document1.pdf','document1.pdf','owner')
    service._statement_service.retrieve_statement_evidence.assert_not_called()
    assert result['response']['answer']=='Uploaded evidence'


def test_case_field_survives_compaction_when_entity_mentions_are_far_away():
    text='HAA case involving Kinga Norbu. '*80 + 'Other form fields. '*100 + 'Case No: | 19/25-26'
    result=answer_from_unified_evidence('what is the case number for HAA case involving Kinga Norbu', [record(text)], Mock())
    assert '19/25-26' in result['answer']
    assert '[owned.pdf, page 1]' in result['answer']


def test_ocr_document_chunk_alias_still_requires_matching_quote():
    raw=json.dumps({'has_information':True,'claims':[{'statement':'The witness owned a sawmill.',
         'evidence':[{'evidence_id':'doc:p1-c1','quote':'I owned a sawmill.'}]}],'missing_information':[]})
    result=answer_from_unified_evidence('What business?', [record('I owned a sawmill.')], lambda *a,**k:raw)
    assert '[owned.pdf, page 1]' in result['answer']
    assert result['sources'][0]['quotes']==['I owned a sawmill.']
    result=answer_from_unified_evidence('What business?', [record('I owned a hotel.')], lambda *a,**k:raw)
    assert not result['has_information']
