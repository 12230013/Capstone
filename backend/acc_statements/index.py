import uuid
import time
import json
from pathlib import Path
from threading import Lock

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

try:
    from acc_statements import config
    from acc_statements.ingest import load_docs
except (ImportError, ModuleNotFoundError):
    import config
    from ingest import load_docs

_embedder = None
_client = None
_embedder_lock = Lock()


def get_embedder():
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            model_path = getattr(config, "EMBED_MODEL_PATH", None)
            if model_path is None:
                print(f"  loading embedding model {config.EMBED_MODEL} (first run downloads it)...", flush=True)
                _embedder = SentenceTransformer(config.EMBED_MODEL, device="cpu")
            else:
                _embedder = _load_local_embedder(model_path)
    return _embedder


def _load_local_embedder(model_path: Path):
    """Load a validated local BGE-M3 Sentence-Transformers directory on CPU."""
    model_path = Path(model_path).expanduser().resolve()
    if not model_path.is_dir():
        raise FileNotFoundError(f"EMBED_MODEL_PATH does not exist: {model_path}")
    modules_path = model_path / "modules.json"
    if not modules_path.is_file():
        raise ValueError("EMBED_MODEL_PATH requires Transformer, Pooling, and Normalize modules")
    modules_config = json.loads(modules_path.read_text(encoding="utf-8"))
    if not isinstance(modules_config, list):
        raise ValueError("EMBED_MODEL_PATH has an invalid modules.json")
    module_types = {str(item.get("type", "")): item for item in modules_config if isinstance(item, dict)}
    transformer_item = next((item for item in module_types.values() if item["type"].endswith("Transformer")), None)
    pooling_item = next((item for item in module_types.values() if item["type"].endswith("Pooling")), None)
    normalize_item = next((item for item in module_types.values() if item["type"].endswith("Normalize")), None)
    if not transformer_item or not pooling_item or not normalize_item:
        raise ValueError("EMBED_MODEL_PATH requires Transformer, Pooling, and Normalize modules")

    required_files = ("sentence_bert_config.json", "config.json")
    missing = [name for name in required_files if not (model_path / name).is_file()]
    if missing:
        raise ValueError(f"EMBED_MODEL_PATH is missing required files: {', '.join(missing)}")
    if not any((model_path / name).is_file() for name in ("tokenizer.json", "sentencepiece.bpe.model")):
        raise ValueError("EMBED_MODEL_PATH is missing tokenizer assets")
    if not any((model_path / name).is_file() for name in ("pytorch_model.bin", "model.safetensors")):
        raise ValueError("EMBED_MODEL_PATH is missing model weights")
    sentence_config = json.loads((model_path / "sentence_bert_config.json").read_text(encoding="utf-8"))
    if not isinstance(sentence_config.get("max_seq_length"), int) or not isinstance(sentence_config.get("do_lower_case"), bool):
        raise ValueError("EMBED_MODEL_PATH has invalid sentence-transformers configuration")
    models = __import__("sentence_transformers.models", fromlist=["models"])
    transformer = models.Transformer(
        str(model_path),
        max_seq_length=sentence_config["max_seq_length"],
        do_lower_case=sentence_config["do_lower_case"],
        model_args={"low_cpu_mem_usage": True, "device_map": "cpu"},
    )
    pooling_path = model_path / str(pooling_item.get("path", ""))
    pooling = models.Pooling.load(str(pooling_path))
    if pooling.get_sentence_embedding_dimension() != config.EMBED_DIM:
        raise ValueError(f"Pooling output dimension must be {config.EMBED_DIM}")
    normalize_path = model_path / str(normalize_item.get("path", ""))
    normalize = models.Normalize.load(str(normalize_path))
    return SentenceTransformer(modules=[transformer, pooling, normalize], device="cpu")


def embed(texts: list[str]) -> list[list[float]]:
    started = time.monotonic()
    vectors = get_embedder().encode(texts, normalize_embeddings=True,
                                 batch_size=config.EMBED_BATCH).tolist()
    print(f"Document query embedding completed in {time.monotonic() - started:.1f}s", flush=True)
    return vectors


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(path=config.QDRANT_PATH)   # only one process may open this at a time
    return _client


def make_chunks(sentences: list[dict]) -> list[list[dict]]:
    chunks, i = [], 0
    while i < len(sentences):
        j, size = i, 0
        while j < len(sentences) and (j == i or size + len(sentences[j]["text"]) <= config.CHUNK_MAX_CHARS):
            size += len(sentences[j]["text"]) + 1
            j += 1
        chunks.append(sentences[i:j])
        if j >= len(sentences):
            break
        i = max(j - config.CHUNK_OVERLAP_SENTENCES, i + 1)
    return chunks


def build_index():
    docs = load_docs()
    client = get_client()
    if client.collection_exists(config.COLLECTION):
        client.delete_collection(config.COLLECTION)
    client.create_collection(
        config.COLLECTION,
        vectors_config=models.VectorParams(size=config.EMBED_DIM, distance=models.Distance.COSINE))

    points = []
    for doc in docs:
        h = doc["header"]
        for n, chunk in enumerate(make_chunks(doc["sentences"]), start=1):
            plain = " ".join(s["text"] for s in chunk)
            numbered = "\n".join(f"[{s['id']}] {s['text']}" for s in chunk)
            # context prefix helps retrieval: the vector "knows" whose statement this is
            embed_text = (f"Statement of {h.get('name', '')} dated {h.get('statement_date', '')}, "
                          f"case {h.get('case_no', '')}.\n{plain}")
            points.append({
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc['doc_id']}-chunk{n}")),
                "embed_text": embed_text,
                "payload": {
                    "doc_id": doc["doc_id"],
                    "case_no": h.get("case_no", ""),
                    "person_name": h.get("name", ""),
                    "statement_date": h.get("statement_date", ""),
                    "sentence_ids": [s["id"] for s in chunk],
                    "text_numbered": numbered,
                },
            })
    vectors = embed([p["embed_text"] for p in points])
    client.upsert(config.COLLECTION, points=[
        models.PointStruct(id=p["id"], vector=v, payload=p["payload"])
        for p, v in zip(points, vectors)])
    print(f"  indexed {len(points)} chunks from {len(docs)} statements")


def search(query: str, case_nos=None, doc_ids=None,
           top_k: int = config.TOP_K) -> list[dict]:
    """Search only within explicitly authorized cases."""

    if case_nos is not None and not case_nos:
        return []

    must = []

    if case_nos is not None:
        must.append(
            models.FieldCondition(
                key="case_no",
                match=models.MatchAny(any=list(case_nos))
            )
        )

    if doc_ids:
        must.append(
            models.FieldCondition(
                key="doc_id",
                match=models.MatchAny(any=list(doc_ids))
            )
        )

    must_not = [
        models.FieldCondition(
            key="source_type",
            match=models.MatchValue(value="ocr_document"),
        )
    ]

    res = get_client().query_points(
        config.COLLECTION,
        query=embed([query])[0],
        query_filter=models.Filter(must=must, must_not=must_not),
        limit=top_k,
        with_payload=True
    )

    return [
        {"score": round(p.score, 4), **p.payload}
        for p in res.points
    ]
    
def close_client():
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None
