import os
import json
import sys

import requests
from pydantic import BaseModel, ValidationError

try:
    from acc_statements import config
except (ImportError, ModuleNotFoundError):
    if __package__:
        raise
    import config


def _chat(messages, fmt=None, max_tokens=None) -> str:
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "stream": True,
        "think": False,
        "keep_alive": "30m",                      # keep model loaded between calls
        "options": {
            "temperature": config.LLM_TEMPERATURE,
            "num_gpu": int(os.getenv("OLLAMA_NUM_GPU", "-1")),
            "num_ctx": config.LLM_NUM_CTX,
            "num_predict": config.LLM_MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens,
        },
    }
    if fmt is not None:
        payload["format"] = fmt

    r = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json=payload,
        stream=True,
        timeout=(5, min(config.LLM_IDLE_TIMEOUT, 90)),    # (connect, max silence between chunks)
    )
    if r.status_code == 404:
        raise RuntimeError(f"Ollama 404: {r.text}\nRun: ollama pull {config.LLM_MODEL}")
    r.raise_for_status()

    parts, n = [], 0
    for line in r.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        if chunk.get("error"):
            r.close()
            raise RuntimeError(chunk["error"])
        piece = chunk.get("message", {}).get("content", "")
        parts.append(piece)
        n += 1
        if config.SHOW_PROGRESS and n % 25 == 0:
            sys.stdout.write(f"\r    receiving... {n} stream chunks")
            sys.stdout.flush()
        if chunk.get("done"):
            if chunk.get("done_reason") == "length":
                r.close()
                raise RuntimeError("Ollama truncated the structured response before completion.")
            break
    else:
        r.close()
        raise RuntimeError("Ollama closed the stream before completing the response.")
    r.close()
    if config.SHOW_PROGRESS:
        count = chunk.get("eval_count")
        usage = f"{count} generated tokens" if count is not None else f"{n} stream chunks"
        sys.stdout.write(f"\r    done ({usage})            \n")
    return "".join(parts)


def ask_text(system: str, user: str) -> str:
    return _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=-1,
    )


def ask_json(system: str, user: str, model_cls: type[BaseModel], *, max_tokens=None, retries=None):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    schema = model_cls.model_json_schema()
    last_error = None
    for _ in range((config.LLM_RETRIES if retries is None else retries) + 1):
        raw = _chat(messages, fmt=schema, max_tokens=max_tokens)
        try:
            return model_cls.model_validate_json(raw)
        except ValidationError as e:
            last_error = e
            # Keep retries within the context window; do not append oversized broken JSON.
            messages = [{"role": "system", "content": system},
                        {"role": "user", "content": user + "\nReturn one complete JSON object matching the schema."}]
    raise RuntimeError(f"LLM failed to return valid JSON: {last_error}")
