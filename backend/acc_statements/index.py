import uuid

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

try:
    import config
    from ingest import load_docs
except (ImportError, ModuleNotFoundError):
    from acc_statements import config
    from acc_statements.ingest import load_docs

_embedder = None
_client = None


def get_embedder():
    global _embedder
    if _embedder is None:
        print(f"  loading embedding model {config.EMBED_MODEL} (first run downloads it)...")
        _embedder = SentenceTransformer(config.EMBED_MODEL)
    return _embedder


def embed(texts: list[str]) -> list[list[float]]:
    return get_embedder().encode(texts, normalize_embeddings=True,
                                 batch_size=config.EMBED_BATCH).tolist()


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

    res = get_client().query_points(
        config.COLLECTION,
        query=embed([query])[0],
        query_filter=models.Filter(must=must) if must else None,
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