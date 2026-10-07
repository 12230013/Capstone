import requests

class LLMService:

    def __init__(
        self,
        model_name: str = "mistral:7b-instruct-v0.3-q2_K",
        ollama_url: str = "http://localhost:11434/api/generate"
    ):
        self.model_name = model_name
        self.ollama_url = ollama_url

    def generate(self, prompt: str) -> str:

        if not isinstance(prompt, str):
            raise ValueError("Prompt must be a string.")

        if not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        response = requests.post(
            self.ollama_url,
            json={
                "model": self.model_name,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()

        result = response.json()

        return result["response"].strip()