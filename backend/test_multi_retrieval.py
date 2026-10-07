from app.services.retrieval_service import RetrievalService

retrieval_service = RetrievalService()

queries = [
    "Where did the accused meet the witness?",
    "Where was the interview conducted?",
    "What financial matter was discussed?"
]

for query in queries:
    print("\n" + "=" * 70)
    print("QUERY:", query)
    print("=" * 70)

    results = retrieval_service.retrieve(
        query=query,
        limit=3
    )

    for index, result in enumerate(results, start=1):
        print(f"\nResult {index}")
        print("Score:", result["score"])
        print("Text:", result["text"])
        print("Metadata:", result["metadata"])

retrieval_service.qdrant_service.client.close()