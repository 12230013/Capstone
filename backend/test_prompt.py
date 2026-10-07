from app.services.retrieval_service import RetrievalService
from app.services.prompt_service import PromptService


retrieval_service = RetrievalService()
prompt_service = PromptService()

query = "Where did the accused meet the witness?"

retrieved_chunks = retrieval_service.retrieve(
    query=query,
    limit=3
)

prompt = prompt_service.build_prompt(
    query=query,
    retrieved_chunks=retrieved_chunks
)

print("\n" + "=" * 70)
print("GENERATED PROMPT")
print("=" * 70)
print(prompt)

retrieval_service.qdrant_service.client.close()