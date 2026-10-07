from app.services.retrieval_service import RetrievalService


retrieval_service = RetrievalService()

query = "Where did the accused meet the witness in Investigation Case 004?"

results = retrieval_service.retrieve(
    query=query,
    limit=3
)

print("\n" + "=" * 70)
print("QUERY")
print("=" * 70)

print(query)

print("\n" + "=" * 70)
print("RETRIEVED RESULTS")
print("=" * 70)

for index, result in enumerate(results, start=1):

    print(f"\nResult {index}")
    print("Score:", result["score"])
    print("Source:", result["metadata"].get("filename"))
    print("Text:", result["text"])

retrieval_service.qdrant_service.client.close()