from app.document_processing.document_loader import load_document
from app.document_processing.text_cleaner import clean_text
from app.document_processing.text_chunker import chunk_text
from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService
import hashlib

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

        # Step 2: Clean extracted text
        cleaned_text = clean_text(
            document["text"]
        )

        # Step 3: Create metadata
        metadata = {
            "filename": document["filename"],
            "file_type": document["file_type"]
        }

        if "page_count" in document:
            metadata["page_count"] = document["page_count"]

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

          source_id = f"{document['filename']}_{chunk['chunk_id']}"

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
            "filename": document["filename"],
            "chunks_created": len(chunks)
        }

        