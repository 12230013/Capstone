from app.services.qdrant_service import QdrantService
from qdrant_client.models import Filter, FieldCondition, MatchValue

def delete_chunks_by_filename(filename: str):
    qdrant = QdrantService()
    
    # Delete points where the metadata 'filename' matches the target file
    result = qdrant.client.delete(
        collection_name=qdrant.collection_name,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="metadata.filename",  # matches your nested metadata structure
                    match=MatchValue(value=filename)
                )
            ]
        )
    )
    print(f"Deleted chunks for filename: {filename}. Status: {result.status}")

if __name__ == "__main__":
    target_file = "page_9.png"
    print(f"Clearing {target_file} from Qdrant vector database...")
    delete_chunks_by_filename(target_file)