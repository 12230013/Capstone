"""Validated access to the statement index's shared BGE-M3 embeddings."""

import importlib
import math
from numbers import Real
from typing import Callable, Sequence


EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIMENSION = 1024


class EmbeddingError(RuntimeError):
    """Raised when the shared BGE-M3 embedder cannot produce valid vectors."""


class BGEEmbeddingAdapter:
    def __init__(
        self,
        embed_batch: Callable[[list[str]], Sequence[Sequence[Real]]] | None = None,
    ) -> None:
        self._embed_batch = embed_batch

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list):
            raise ValueError("Texts must be provided as a list.")
        if not texts:
            return []

        normalized_texts = []
        for text in texts:
            if not isinstance(text, str):
                raise ValueError("Every text to embed must be a string.")
            normalized = " ".join(text.split())
            if not normalized:
                raise ValueError("Text to embed cannot be empty.")
            normalized_texts.append(normalized)

        try:
            vectors = self._get_embed_batch()(normalized_texts)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise EmbeddingError("The shared BGE-M3 embedding call failed.") from exc

        if not isinstance(vectors, Sequence) or isinstance(vectors, (str, bytes)):
            raise EmbeddingError("BGE-M3 returned an invalid embedding batch.")
        if len(vectors) != len(normalized_texts):
            raise EmbeddingError(
                "BGE-M3 returned a different number of vectors than input texts."
            )

        validated_vectors = []
        for vector in vectors:
            if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
                raise EmbeddingError("BGE-M3 returned an invalid embedding vector.")
            if len(vector) != EMBEDDING_DIMENSION:
                raise EmbeddingError(
                    f"BGE-M3 vectors must contain {EMBEDDING_DIMENSION} dimensions."
                )
            if any(
                isinstance(value, bool)
                or not isinstance(value, Real)
                or not math.isfinite(float(value))
                for value in vector
            ):
                raise EmbeddingError(
                    "BGE-M3 vectors must contain only finite numeric values."
                )
            validated_vectors.append([float(value) for value in vector])
        return validated_vectors

    def _get_embed_batch(
        self,
    ) -> Callable[[list[str]], Sequence[Sequence[Real]]]:
        if self._embed_batch is not None:
            return self._embed_batch

        try:
            index = importlib.import_module("acc_statements.index")
        except ImportError as exc:
            raise EmbeddingError(
                "The existing statement BGE-M3 index is unavailable."
            ) from exc

        if index.config.EMBED_MODEL != EMBEDDING_MODEL:
            raise EmbeddingError(
                "The statement index is not configured for BAAI/bge-m3."
            )
        if index.config.EMBED_DIM != EMBEDDING_DIMENSION:
            raise EmbeddingError(
                f"The statement index must use {EMBEDDING_DIMENSION}-dimensional vectors."
            )
        return index.embed
