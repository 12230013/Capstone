import re

from llama_index.core import VectorStoreIndex
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient


class RetrievalService:
    def __init__(self):
        # Connect to the existing local Qdrant database
        self.qdrant_client = QdrantClient(
            path="qdrant_storage"
        )

        # Use the existing Qdrant collection
        self.vector_store = QdrantVectorStore(
            client=self.qdrant_client,
            collection_name="investigation_documents"
        )

        # Use the same embedding model as the existing RAG system
        self.embed_model = HuggingFaceEmbedding(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        # Create LlamaIndex around the EXISTING vector store
        self.index = VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            embed_model=self.embed_model
        )

        # Retriever only.
        # LLM generation will still be handled by our existing LLMService.
        self.retriever = self.index.as_retriever(
            similarity_top_k=10
        )

    def retrieve(
        self,
        query: str,
        limit: int = 5
    ) -> list[dict]:

        if not isinstance(query, str):
            raise ValueError("Query must be a string.")

        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if limit <= 0:
            raise ValueError("Limit must be greater than 0.")

        # ---------------------------------------------------------
        # Detect investigation case from the user's query
        # ---------------------------------------------------------

        case_match = re.search(
            r"investigation\s+case\s+(\d+)",
            query,
            re.IGNORECASE
        )

        case_number = None

        if case_match:
            case_number = case_match.group(1).zfill(3)

        # ---------------------------------------------------------
        # LlamaIndex performs the vector retrieval
        # ---------------------------------------------------------

        retrieved_nodes = self.retriever.retrieve(query)

        retrieved_chunks = []

        for node in retrieved_nodes:

            metadata = node.metadata or {}

            retrieved_chunks.append({
                "score": node.score if node.score is not None else 0.0,
                "text": node.get_content(),
                "metadata": metadata
            })

        # ---------------------------------------------------------
        # Preserve existing investigation-case prioritization
        # ---------------------------------------------------------

        if case_number:

            target_filename = f"case_{case_number}.txt"

            case_chunks = [
                 chunk
                 for chunk in retrieved_chunks
                 if chunk["metadata"].get(
                     "metadata",
                     {}
                 ).get("filename",
                        ""
                 ).lower() == target_filename.lower()
            ]

            if case_chunks:
                retrieved_chunks = case_chunks

        else:

            retrieved_chunks.sort(
                key=lambda item: -item["score"]
            )

        # ---------------------------------------------------------
        # Return only the requested number of chunks
        # ---------------------------------------------------------

        return retrieved_chunks[:limit]

    def close(self):
        self.qdrant_client.close()