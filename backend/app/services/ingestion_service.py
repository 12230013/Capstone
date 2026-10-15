from app.document_processing.document_loader import load_document
from app.document_processing.text_chunker import chunk_text
from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService
from app.ocr.document_postprocessing import clean_text_for_rag
from app.ocr.document_ocr import run_document_ocr
import hashlib
import os
from uuid import uuid4

class IngestionService:
    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.qdrant_service = QdrantService()

    def ingest_document(self, file_path: str):
        """
        Load, clean, chunk, embed, and store a document.
        """

        # Step 1: Load document
        document = load_document(file_path)
        extracted_text = document.get("text", "")

        # Fallback to PaddleOCR-VL if the native digital text layer is empty (scanned PDFs / images)
        if not extracted_text.strip():
            filename = document.get("filename", os.path.basename(file_path))
            raw_file_type = document.get("file_type", "pdf").lower()
            
            # Normalize file_type to standard MIME types expected by OCR module
            if "pdf" in raw_file_type:
                file_type = "application/pdf"
            elif "png" in raw_file_type:
                file_type = "image/png"
            elif "jpg" in raw_file_type or "jpeg" in raw_file_type:
                file_type = "image/jpeg"
            else:
                file_type = "application/pdf"

            doc_id = str(uuid4())

            ocr_result = run_document_ocr(
                file_path=file_path,
                document_id=doc_id,
                filename=filename,
                file_type=file_type
            )
            
            # Extract text from OCR result pages
            pages = ocr_result.get("pages", [])
            extracted_text = "\n\n".join(page.get("text", "") for page in pages)
            document["file_type"] = file_type
            document["filename"] = filename

        # Step 2: Clean extracted text
        cleaned_text = clean_text_for_rag(
            extracted_text
        )

        # Step 3: Create metadata
        metadata = {
            "filename": document.get("filename"),
            "file_type": document.get("file_type")
        }

        if "page_count" in document:
            metadata["page_count"] = document["page_count"]

        # Preserve ACC statement metadata if present
        for field in ["is_statement", "person_name", "cid", "phone_number", "occupation"]:
            if field in document:
                metadata[field] = document[field]
        if "statement_metadata" in document and isinstance(document["statement_metadata"], dict):
            metadata["statement_metadata"] = document["statement_metadata"]

        # Step 4: Create chunks
        chunks = chunk_text(
            cleaned_text,
            chunk_size=500,
            overlap=50,
            metadata=metadata
        )

        # Step 5: Create embeddings
        texts = [
            chunk["text"]
            for chunk in chunks
        ]

        embeddings = (
            self.embedding_service.create_embeddings(
                texts
            )
        )

        # Step 6: Store chunks in Qdrant
        for chunk, embedding in zip(
            chunks,
            embeddings
        ):

            source_id = f"{document.get('filename', 'doc')}_{chunk['chunk_id']}"

            point_id = hashlib.md5(
                source_id.encode("utf-8")
            ).hexdigest()

            self.qdrant_service.add_chunk(
                text=chunk["text"],
                embedding=embedding,
                metadata={
                    **chunk["metadata"],
                    "chunk_id": chunk["chunk_id"]
                },
                point_id=point_id
            )
            
        return {
            "filename": document.get("filename"),
            "chunks_created": len(chunks)
        }