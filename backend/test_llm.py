from app.services.llm_service import LLMService


llm_service = LLMService()

prompt = """
You are an AI assistant supporting authorized investigators.

Answer the following question in one sentence.

Question:
What is the purpose of an investigation?

Answer:
"""

answer = llm_service.generate(prompt)

print("\n" + "=" * 70)
print("LLM RESPONSE")
print("=" * 70)
print(answer)