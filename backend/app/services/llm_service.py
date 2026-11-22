import os
import json
import time
import requests


class LLMService:

    def __init__(
        self,
        model_name: str = "mistral:7b-instruct-v0.3-q2_K",
        ollama_url: str = "http://localhost:11434/api/generate"
    ):
        self.model_name = os.getenv("OLLAMA_MODEL") or model_name
        self.ollama_url = ollama_url

    def generate(self, prompt: str, max_tokens: int = -1, response_format=None) -> str:

        if not isinstance(prompt, str):
            raise ValueError("Prompt must be a string.")

        if not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        started = time.monotonic()
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": True,
            "think": False,
            "keep_alive": "30m",
            "options": {
                "num_predict": max_tokens, "num_ctx": 4096,
                "num_gpu": int(os.getenv("OLLAMA_NUM_GPU", "-1")),
            },
        }
        if response_format is not None:
            payload["format"] = response_format
            payload["options"]["temperature"] = 0
        response = requests.post(self.ollama_url, json=payload, stream=True, timeout=(5, 90))

        # Show Ollama's actual error instead of hiding it
        if response.status_code != 200:
            print("\nOllama Error:")
            print(response.text)

        try:
            response.raise_for_status()
            parts = []
            for line in response.iter_lines(chunk_size=1):
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise RuntimeError(chunk["error"])
                parts.append(chunk.get("response", ""))
                if chunk.get("done"):
                    answer = "".join(parts).strip()
                    if chunk.get("done_reason") == "length":
                        answer += "\n\n*Response length limit reached. Ask a focused follow-up for more detail.*"
                    print(f"Model generation completed in {time.monotonic() - started:.1f}s")
                    return answer
            raise RuntimeError("Ollama closed the stream before completing the answer.")
        finally:
            response.close()
