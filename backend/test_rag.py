from app.services.rag_service import RAGService

def test_rag_flow():
    print("Initializing RAGService...")
    rag_service = RAGService()
    
    query = "Who studied in university?"
    print(f"Asking query: '{query}'\n")
    
    response = rag_service.query(query=query, limit=2)
    
    print("=== LLM ANSWER ===")
    print(response.get("answer"))
    
    print("\n=== SOURCES CITED ===")
    for source in response.get("sources", []):
        print(f"- Filename: {source.get('filename')}")
        print(f"  Excerpt: {source.get('excerpt')}")

if __name__ == "__main__":
    test_rag_flow()