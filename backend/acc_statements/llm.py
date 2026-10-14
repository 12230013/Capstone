import json
import sys

import requests
from pydantic import BaseModel, ValidationError

try:
    import config
except (ImportError, ModuleNotFoundError):
    from acc_statements import config


def _chat(messages, fmt=None) -> str:
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "stream": True,
        "keep_alive": "30m",                      # keep model loaded between calls
        "options": {
            "temperature": config.LLM_TEMPERATURE,
            "num_ctx": config.LLM_NUM_CTX,
            "num_predict": config.LLM_MAX_OUTPUT_TOKENS,
        },
    }
    if fmt is not None:
        payload["format"] = fmt

    r = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json=payload,
        stream=True,
        timeout=(10, config.LLM_IDLE_TIMEOUT),    # (connect, max silence between chunks)
    )
    if r.status_code == 404:
        raise RuntimeError(f"Ollama 404: {r.text}\nRun: ollama pull {config.LLM_MODEL}")
    r.raise_for_status()

    parts, n = [], 0
    for line in r.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        piece = chunk.get("message", {}).get("content", "")
        parts.append(piece)
        n += 1
        if config.SHOW_PROGRESS and n % 25 == 0:
            sys.stdout.write(f"\r    generating... {n} tokens")
            sys.stdout.flush()
        if chunk.get("done"):
            break
    if config.SHOW_PROGRESS:
        sys.stdout.write(f"\r    done ({n} tokens)            \n")
    return "".join(parts)


def ask_text(system: str, user: str) -> str:
    return _chat([{"role": "system", "content": system}, {"role": "user", "content": user}])


def ask_json(system: str, user: str, model_cls: type[BaseModel]):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    schema = model_cls.model_json_schema()
    last_error = None
    for _ in range(config.LLM_RETRIES + 1):
        raw = _chat(messages, fmt=schema)
        try:
            return model_cls.model_validate_json(raw)
        except ValidationError as e:
            last_error = e
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"Your JSON was invalid: {e}. Return corrected JSON only."}]
    raise RuntimeError(f"LLM failed to return valid JSON: {last_error}")

