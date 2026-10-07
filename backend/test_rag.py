from app.services.retrieval_service import RetrievalService
from app.services.prompt_service import PromptService
from app.services.llm_service import LLMService


retrieval_service = RetrievalService()
prompt_service = PromptService()
llm_service = LLMService()


#query = "Where did the accused meet the witness?"
#query = " Where did the accused meet the witness in Investigation Case 002"
#query = "What was the amount of the financial transaction in Investigation Case 002?"
#query = "What financial matter was discussed in Investigation Case 002?"
#query = "When did the meeting in Investigation Case 002 take place?"
query = "Where and when did the accused meet the witness in Investigation Case 002, and how long did the meeting last?"

# Step 1: Retrieve relevant evidence
retrieved_chunks = retrieval_service.retrieve(
    query=query,
    limit=3
)


print("\n" + "=" * 70)
print("RETRIEVED EVIDENCE")
print("=" * 70)

for index, chunk in enumerate(retrieved_chunks, start=1):
    print(f"\nEvidence {index}")
    print("Score:", chunk["score"])
    print("Source:", chunk["metadata"].get("filename"))
    print("Text:", chunk["text"])


# Step 2: Build the prompt
prompt = prompt_service.build_prompt(
    query=query,
    retrieved_chunks=retrieved_chunks
)


# Step 3: Generate answer using Mistral
answer = llm_service.generate(prompt)


print("\n" + "=" * 70)
print("GENERATED ANSWER")
print("=" * 70)
print(answer)


retrieval_service.qdrant_service.client.close()