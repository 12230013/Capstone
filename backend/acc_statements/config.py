from pathlib import Path

# ---------- paths ----------
_this_dir = Path(__file__).resolve().parent
# _candidates = [
#     Path("data/statements"),
#     Path("app/statement_documents"),
#     _this_dir / "data" / "statements",
#     _this_dir.parent / "app" / "statement_documents",
# ]
# DATA_DIR = next((p for p in _candidates if p.exists()), _this_dir.parent / "app" / "statement_documents")

from pathlib import Path

# Always load statements from this RAG project's own data folder.
_this_dir = Path(__file__).resolve().parent

DATA_DIR = _this_dir / "data" / "statements"


OUTPUT_DIR = _this_dir / "outputs"
PARSED_DIR = OUTPUT_DIR / "parsed"
QDRANT_PATH = str(_this_dir / "qdrant_db")            # local on-disk Qdrant (no Docker needed)
COLLECTION = "statements"

# ---------- LLM (Ollama) ----------
OLLAMA_URL = "http://localhost:11434"
LLM_MODEL = "mistral:7b-instruct-v0.3-q2_K"                # try "qwen2.5:7b" or "llama3.1:8b" if JSON is unreliable
LLM_TEMPERATURE = 0.0                # 0 = deterministic, what you want for evidence work
LLM_NUM_CTX = 4096                   # context window; raise if statements are long
LLM_TIMEOUT = 300                    # seconds
LLM_RETRIES = 2                      # re-ask if the JSON fails validation

# ---------- embeddings ----------
EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIM = 1024
EMBED_BATCH = 16

# ---------- chunking / retrieval ----------
CHUNK_MAX_CHARS = 1200
CHUNK_OVERLAP_SENTENCES = 1
TOP_K = 6

# ---------- analysis ----------
SUMMARY_SENTENCES = 6
SUMMARY_WARN_CHARS = 15000           # warn if a statement may not fit the context window

# ---------- contradiction detection ----------
CLAIM_PAIR_THRESHOLD = 0.55          # min cosine similarity for two claims to be compared
CLAIMS_PER_NEIGHBOUR = 3             # compare each claim to its N most similar claims in other statements
COMPARE_SAME_DOC = False             # set True to also look for self-contradiction inside one statement
MAX_PAIRS = 80                       # cap LLM judge calls

DISCLAIMER = ("AI-generated analytical aid. Flags are for investigator review and are "
              "not findings of fact. Verify against the original statements.")

LLM_IDLE_TIMEOUT = 600          # seconds of silence before giving up (not total time)
LLM_MAX_OUTPUT_TOKENS = 2048    # hard cap so one call can't ramble forever
SHOW_PROGRESS = True

import atexit
