"""Test-only application with real MongoDB and controlled external model responses."""
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from uuid import uuid4

import requests

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "acceptance.json"
DATA = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
DATABASE_NAME = os.environ.get("MONGO_DB_NAME", "acc_test_" + uuid4().hex)
RUN_ID = os.environ.get("ACC_TEST_RUN_ID", uuid4().hex)
if not DATABASE_NAME.startswith("acc_test_"):
    raise RuntimeError("Integration tests require a disposable acc_test_ database.")

# Set these before importing the application's database and settings modules.
os.environ["MONGO_DB_NAME"] = DATABASE_NAME
os.environ["MONGO_URI"] = os.environ.get("TEST_MONGO_URI", "mongodb://127.0.0.1:27017")
os.environ["ENVIRONMENT"] = "development"
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["SESSION_HOURS"] = "8"
os.environ["SESSION_IDLE_MINUTES"] = "30"
os.environ["FRONTEND_ORIGINS"] = "http://127.0.0.1:5181,http://localhost:5181,http://localhost:5173"

from app.services.evidence_grounding import answer_from_evidence


class ControlledChatService:
    """Replace only the external answer service, preserving production route logic."""
    def __init__(self):
        self.retry_failed = False

    async def query(self, query, context=None):
        questions = DATA["questions"]
        if query == questions["retry"] and not self.retry_failed:
            self.retry_failed = True
            raise requests.Timeout("Simulated temporary model failure")
        supported = query in (questions["supported"], questions["retry"])
        document = DATA["document"]

        def generate(prompt, response_format=None):
            return json.dumps({
                "has_information": supported,
                "claims": [{"statement": document["text"], "evidence": [{
                    "sentence_id": document["sentence_id"], "quote": document["text"],
                }]}] if supported else [],
                "missing_information": [] if supported else ["bank account number"],
            })

        grounded = answer_from_evidence(query, {document["sentence_id"]: document["text"]}, generate)
        sources = [{
            "doc_id": document["doc_id"], "filename": document["filename"],
            "case_no": document["case_no"], "sentence_ids": [document["sentence_id"]],
            "excerpt": document["text"],
        }] if grounded["has_information"] else []
        return {"success": True, "response": {"answer": grounded["answer"], "sources": sources}}


class ControlledTitleService:
    def generate(self, prompt, max_tokens=-1):
        return DATA["title"]


# Avoid loading the large embedding model in this isolated test process.
service_module = ModuleType("app.services.chat_service")
service_module.ChatService = ControlledChatService
sys.modules["app.services.chat_service"] = service_module

from app.main import app
from app.database.connection import client, db
from app.api.routes import chat, sources
from integration_tests.cleanup import remove_owned_database

chat.LLMService = ControlledTitleService


@asynccontextmanager
async def integration_lifespan(application):
    client.admin.command("ping")
    if db.list_collection_names():
        raise RuntimeError("Refusing to reuse a nonempty integration database.")
    db.integration_test_runs.insert_one({"_id": RUN_ID, "fixture": "synthetic acceptance"})
    document = DATA["document"]
    with TemporaryDirectory(prefix="acc_acceptance_") as directory:
        root = Path(directory)
        (root / document["filename"]).write_text(document["text"], encoding="utf-8")
        (root / (document["doc_id"] + ".json")).write_text(json.dumps({"sentences": [{
            "id": document["sentence_id"], "text": document["text"],
        }]}), encoding="utf-8")
        sources.DATA_DIR = root
        sources.PARSED_DIR = root
        print(f"Integration database ready: {DATABASE_NAME}", flush=True)
        try:
            yield
        finally:
            # Only the database allocated above may be removed by this test server.
            if db.name == DATABASE_NAME:
                remove_owned_database(client, DATABASE_NAME, RUN_ID)
            client.close()


app.router.lifespan_context = integration_lifespan
