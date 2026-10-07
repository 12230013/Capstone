from app.services.embedding_service import EmbeddingService

embedding_service = EmbeddingService()

text = """
The witness stated that the meeting occurred in Thimphu.
"""

embedding = embedding_service.create_embedding(text)

print("Embedding length:", len(embedding))
print("First 10 values:", embedding[:10])