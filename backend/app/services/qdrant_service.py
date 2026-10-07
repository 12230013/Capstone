from uuid import uuid4
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct
)

class QdrantService:
    def __init__(
        self,
        storage_path: str = "qdrant_storage",
        collection_name: str = "investigation_documents"
    ):
        self.client = QdrantClient(
            path=storage_path
        )

        self.collection_name = collection_name

        self._create_collection()

    def _create_collection(self):
        """
        Create the Qdrant collection if it does not already exist.
        """

        if not self.client.collection_exists(
            self.collection_name
        ):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=384,
                    distance=Distance.COSINE
                )
            )

    def add_chunk(
        self,
        text: str,
        embedding: list[float],
        metadata: dict,
        point_id: str
    ):
        point = PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "text": text,
                "metadata": metadata
         }
     )

        self.client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )

        return point_id
    
    def search(
        self,
        query_embedding: list[float],
        limit: int = 5
    ):
        """
        Search Qdrant for the most similar document chunks.
        """

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )

        return results.points