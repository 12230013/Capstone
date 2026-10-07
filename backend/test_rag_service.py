from app.services.rag_service import RAGService


rag_service = RAGService()


query = "Where did the accused meet the witness in Investigation Case 002?"


result = rag_service.query(
    query=query,
    limit=3
)


print("\n" + "=" * 70)
print("ANSWER")
print("=" * 70)

print(result["answer"])


print("\n" + "=" * 70)
print("SOURCES")
print("=" * 70)

for source in result["sources"]:
    print(
        f"Source: {source['filename']}"
    )
    print(
        f"Score: {source['score']}"
    )


rag_service.retrieval_service.qdrant_service.client.close()