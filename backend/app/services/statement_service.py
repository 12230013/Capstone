import sys
import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure acc_statements and backend are on sys.path
_this_file = Path(__file__).resolve()
_backend_dir = _this_file.parent.parent.parent
_acc_dir = _backend_dir / "acc_statements"

for _p in [_backend_dir, _acc_dir]:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from acc_statements.statement_parser import StatementParser
except ImportError:
    try:
        from statement_parser import StatementParser
    except ImportError:
        StatementParser = None


class StatementService:
    def __init__(
        self,
        statements_dir: Optional[str] = None,
        storage_path: str = "qdrant_storage"
    ):
        # Resolve statements directory from known paths
        candidates = []
        if statements_dir:
            candidates.append(Path(statements_dir))

        candidates.extend([
            _backend_dir / "app" / "statement_documents",
            _acc_dir / "data" / "statements",
            Path("app/statement_documents"),
            Path("data/statements"),
        ])

        self.statements_dir = next((p for p in candidates if p.exists()), _backend_dir / "app" / "statement_documents")
        self.storage_path = storage_path
        self.parser = StatementParser() if StatementParser else None

        self._embedding_service = None
        self._qdrant_service = None
        self._retrieval_service = None
        self._prompt_service = None
        self._llm_service = None

    @property
    def embedding_service(self):
        if self._embedding_service is None:
            try:
                from app.services.embedding_service import EmbeddingService
                self._embedding_service = EmbeddingService()
            except Exception as e:
                print(f"EmbeddingService warning: {e}")
        return self._embedding_service

    @property
    def qdrant_service(self):
        if self._qdrant_service is None:
            try:
                from app.services.qdrant_service import QdrantService
                self._qdrant_service = QdrantService(storage_path=self.storage_path)
            except Exception as e:
                print(f"QdrantService warning: {e}")
        return self._qdrant_service

    @property
    def retrieval_service(self):
        if self._retrieval_service is None:
            try:
                from app.services.retrieval_service import RetrievalService
                self._retrieval_service = RetrievalService()
            except Exception as e:
                print(f"RetrievalService warning: {e}")
        return self._retrieval_service

    @property
    def prompt_service(self):
        if self._prompt_service is None:
            try:
                from app.services.prompt_service import PromptService
                self._prompt_service = PromptService()
            except Exception as e:
                print(f"PromptService warning: {e}")
        return self._prompt_service

    @property
    def llm_service(self):
        if self._llm_service is None:
            try:
                from app.services.llm_service import LLMService
                self._llm_service = LLMService()
            except Exception as e:
                print(f"LLMService warning: {e}")
        return self._llm_service

    def get_parsed_doc(self, file_path: Path) -> dict:
        """Parse statement with sentence IDs and structured header using acc_statements.ingest."""
        try:
            try:
                from acc_statements.ingest import parse_statement
            except ImportError:
                from ingest import parse_statement
            return parse_statement(file_path)
        except Exception:
            # Fallback parser
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            if self.parser:
                parsed = self.parser.parse_text(text, filename=file_path.name)
                header = parsed.get("metadata", {})
                body = parsed.get("body", text)
            else:
                header = {}
                body = text

            sentences = [
                {"id": f"{file_path.stem}-s{idx}", "text": s.strip()}
                for idx, s in enumerate(re.split(r'(?<=[.!?])\s+', body), 1)
                if s.strip()
            ]
            return {
                "doc_id": file_path.stem,
                "source_file": file_path.name,
                "header": header,
                "sentences": sentences
            }

    def load_statement_docs(self) -> List[dict]:
        """Loads and parses all statement files."""
        if not self.statements_dir.exists():
            return []
        docs = []
        for file in sorted(self.statements_dir.glob("*.txt")):
            try:
                docs.append(self.get_parsed_doc(file))
            except Exception as e:
                print(f"Warning parsing {file}: {e}")
        return docs

    def list_statements(self) -> List[Dict[str, Any]]:
        """List all statement documents with parsed metadata."""
        if not self.statements_dir.exists():
            return []

        results = []
        for file in sorted(self.statements_dir.glob("*.txt")):
            doc = self.get_parsed_doc(file)
            h = doc.get("header", {})
            dz = h.get("dzongkhag") or h.get("dzongkhang") or "Unknown"
            results.append({
                "statement_id": doc.get("doc_id", file.stem),
                "filename": file.name,
                "name": h.get("name") or "Unknown",
                "cid": h.get("cid") or "Unknown",
                "occupation": h.get("occupation") or "Unknown",
                "phone_number": h.get("phone_number") or h.get("phone") or "Unknown",
                "gender": h.get("gender") or "Unknown",
                "dob": h.get("dob") or "Unknown",
                "village": h.get("village") or "Unknown",
                "gewog": h.get("gewog") or "Unknown",
                "dzongkhag": dz,
                "dzongkhang": dz,
                "case_no": h.get("case_no") or "Unknown",
                "statement_date": h.get("statement_date") or h.get("date") or "Unknown",
                "sentence_count": len(doc.get("sentences", [])),
                "file_path": str(file)
            })
        return results

    def get_statement(self, statement_id: str) -> Dict[str, Any]:
        """Fetch full parsed statement including sentences and metadata."""
        file_path = self.statements_dir / f"{statement_id}.txt"
        if not file_path.exists():
            matches = list(self.statements_dir.glob(f"*{statement_id}*.txt"))
            if matches:
                file_path = matches[0]
            else:
                raise FileNotFoundError(f"Statement '{statement_id}' not found.")

        doc = self.get_parsed_doc(file_path)
        raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
        body_text = " ".join(s["text"] for s in doc.get("sentences", []))
        return {
            "statement_id": doc.get("doc_id", file_path.stem),
            "filename": file_path.name,
            "header": doc.get("header", {}),
            "sentences": doc.get("sentences", []),
            "body": body_text or raw_text,
            "raw_text": raw_text,
            "person_name": doc.get("header", {}).get("name", "Unknown"),
            "cid": doc.get("header", {}).get("cid", "Unknown"),
        }

    def ingest_statements(self) -> Dict[str, Any]:
        """Ingest and index all statements into vector storage for RAG."""
        docs = self.load_statement_docs()
        if not docs:
            return {"status": "error", "message": "No statement documents found to ingest."}

        # Try building index using acc_statements.index if available
        try:
            try:
                from acc_statements.index import build_index
            except ImportError:
                from index import build_index
            build_index()
            return {
                "status": "success",
                "engine": "acc_statements_qdrant",
                "indexed_statements": len(docs),
                "statement_ids": [d["doc_id"] for d in docs]
            }
        except Exception as e:
            print(f"acc_statements build_index fallback to QdrantService: {e}")

        # Fallback ingestion using Capstone QdrantService and chunker
        try:
            from app.document_processing.text_cleaner import clean_text
            from app.document_processing.text_chunker import chunk_text

            ingested_count = 0
            for doc in docs:
                h = doc.get("header", {})
                plain_text = " ".join(s["text"] for s in doc.get("sentences", []))
                cleaned = clean_text(plain_text)
                meta = {
                    "filename": doc.get("source_file", f"{doc['doc_id']}.txt"),
                    "file_type": "txt",
                    "doc_type": "statement",
                    "statement_id": doc["doc_id"],
                    "name": h.get("name", ""),
                    "cid": h.get("cid", ""),
                    "case_no": h.get("case_no", ""),
                    "statement_date": h.get("statement_date", ""),
                }

                chunks = chunk_text(cleaned, chunk_size=400, overlap=40, metadata=meta)
                if chunks and self.embedding_service and self.qdrant_service:
                    texts = [c["text"] for c in chunks]
                    embeddings = self.embedding_service.create_embeddings(texts)
                    for c, emb in zip(chunks, embeddings):
                        import hashlib
                        pid = hashlib.md5(f"{doc['doc_id']}_{c['chunk_id']}".encode()).hexdigest()
                        self.qdrant_service.add_chunk(
                            text=c["text"],
                            embedding=emb,
                            metadata=c["metadata"],
                            point_id=pid
                        )
                ingested_count += 1

            return {
                "status": "success",
                "engine": "qdrant_service",
                "indexed_statements": ingested_count,
                "statement_ids": [d["doc_id"] for d in docs]
            }
        except Exception as ex:
            return {"status": "error", "message": str(ex)}

    def query_statement_evidence(self, query: str, limit: int = 4, case_nos: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Executes verified sentence-level RAG query over statements.
        Cites source sentences as [stmt_01-s4] and validates citations against source text.
        """
        # First try acc_statements.chat.ask
        try:
            try:
                from acc_statements.chat import ask
            except ImportError:
                from chat import ask

            result = ask(question=query, case_nos=case_nos)
            return {
                "success": True,
                "engine": "acc_statements_rag",
                "answer": result.get("answer", ""),
                "sources": result.get("sources", []),
                "retrieved": result.get("retrieved", []),
                "warnings": result.get("warnings", []),
                "disclaimer": result.get("disclaimer", "")
            }
        except Exception as e:
            print(f"acc_statements ask fallback: {e}")

        # Fallback to Capstone RAG services
        if self.retrieval_service and self.prompt_service and self.llm_service:
            retrieved_chunks = self.retrieval_service.retrieve(query=query, limit=limit)
            prompt = self.prompt_service.build_prompt(query=query, retrieved_chunks=retrieved_chunks)
            answer = self.llm_service.generate(prompt)

            sources = []
            for chunk in retrieved_chunks:
                meta = chunk.get("metadata", {})
                sources.append({
                    "filename": meta.get("filename", "statement.txt"),
                    "statement_id": meta.get("statement_id"),
                    "name": meta.get("name"),
                    "score": chunk.get("score")
                })

            return {
                "success": True,
                "engine": "fallback_rag",
                "answer": answer,
                "sources": sources,
                "retrieved": retrieved_chunks,
                "warnings": [],
                "disclaimer": "AI-generated analytical aid. Verify against original statements."
            }

        return {
            "success": False,
            "answer": "Unable to execute query: RAG services not available.",
            "sources": [],
            "warnings": ["RAG backend is offline"]
        }

    def detect_contradictions(self, statement_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Runs contradiction detection across statement documents.
        Uses claim extraction, embedding similarity pairing, and LLM judge from acc_statements.
        """
        docs = self.load_statement_docs()
        if statement_ids:
            docs = [d for d in docs if d["doc_id"] in statement_ids]

        if not docs:
            return {"analyzed_statements": [], "contradictions": [], "warnings": ["No statements found"]}

        # 1. Deterministic metadata checks (CID/DOB mismatch, case number differences)
        meta_issues = []
        try:
            try:
                from acc_statements.contradictions import metadata_checks
            except ImportError:
                from contradictions import metadata_checks
            meta_issues = metadata_checks(docs)
        except Exception as e:
            print(f"metadata_checks error: {e}")

        # 2. LLM contradiction detector from acc_statements
        try:
            try:
                from acc_statements.contradictions import detect_contradictions as run_detect
            except ImportError:
                from contradictions import run_detect
            detector_result = run_detect(docs)
            return {
                "success": True,
                "engine": "acc_statements_contradictions",
                "analyzed_statements": [d["doc_id"] for d in docs],
                "metadata_issues": meta_issues,
                "contradictions": detector_result.get("contradictions", []),
                "different_detail": detector_result.get("different_detail", []),
                "disclaimer": detector_result.get("disclaimer", "")
            }
        except Exception as e:
            print(f"acc_statements detect_contradictions fallback: {e}")

        # Fallback to app.statement_analysis.contradiction_detector if Ollama not running
        try:
            from app.statement_analysis.contradiction_detector import ContradictionDetector
            detector = ContradictionDetector()
            payload = [
                {
                    "statement_id": d["doc_id"],
                    "id": d["doc_id"],
                    "name": d.get("header", {}).get("name", "Unknown"),
                    "text": " ".join(s["text"] for s in d.get("sentences", []))
                }
                for d in docs
            ]
            raw_res = detector.analyze(payload)
            parsed_res = json.loads(raw_res) if isinstance(raw_res, str) else raw_res
            return {
                "success": True,
                "engine": "fallback_contradictions",
                "analyzed_statements": [d["doc_id"] for d in docs],
                "metadata_issues": meta_issues,
                "result": parsed_res
            }
        except Exception as ex:
            return {
                "success": False,
                "analyzed_statements": [d["doc_id"] for d in docs],
                "metadata_issues": meta_issues,
                "error": str(ex)
            }

    def summarize_statement(self, statement_id: str) -> Dict[str, Any]:
        """Summarize a statement with cited key points."""
        docs = self.load_statement_docs()
        doc = next((d for d in docs if d["doc_id"] == statement_id), None)
        if not doc:
            raise FileNotFoundError(f"Statement '{statement_id}' not found.")

        try:
            try:
                from acc_statements.analyze import summarize, extract_entities
            except ImportError:
                from analyze import summarize, extract_entities
            res_summary = summarize(doc)
            res_entities = extract_entities(doc)
            return {
                "success": True,
                "statement_id": statement_id,
                "summary": res_summary.get("summary", ""),
                "key_points": res_summary.get("key_points", []),
                "entities": res_entities.get("entities", [])
            }
        except Exception as e:
            return {
                "success": False,
                "statement_id": statement_id,
                "error": str(e)
            }

    def build_timeline(self, case_no: Optional[str] = None) -> List[Dict[str, Any]]:
        """Builds a chronological timeline of events across statements."""
        docs = self.load_statement_docs()
        if case_no:
            docs = [d for d in docs if d.get("header", {}).get("case_no") == case_no]

        try:
            try:
                from acc_statements.analyze import build_case_timeline
            except ImportError:
                from analyze import build_case_timeline
            return build_case_timeline(docs)
        except Exception as e:
            print(f"build_case_timeline error: {e}")
            return []
