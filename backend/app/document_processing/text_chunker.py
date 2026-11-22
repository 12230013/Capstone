import re


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    metadata: dict | None = None
) -> list[dict]:
    """
    Split text into sentence-aware overlapping chunks
    and attach metadata to each chunk.
    """

    if not isinstance(text, str):
        raise ValueError("Text must be a string.")

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")

    if overlap < 0:
        raise ValueError("overlap cannot be negative.")

    if overlap >= chunk_size:
        raise ValueError(
            "overlap must be smaller than chunk_size."
        )

    text = text.strip()

    if not text:
        return []

    # Split text into sentences
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]

    chunks = []
    current_sentences = []
    current_length = 0

    for sentence in sentences:
        sentence_length = len(sentence)

        if (
            current_sentences
            and current_length + sentence_length + 1 > chunk_size
        ):
            chunk_text_value = " ".join(current_sentences)

            chunks.append({
                "chunk_id": len(chunks) + 1,
                "text": chunk_text_value,
                "metadata": metadata.copy() if metadata else {}
            })

            # Create sentence-level overlap
            overlap_sentences = []
            overlap_length = 0

            for previous_sentence in reversed(current_sentences):
                if (
                    overlap_length
                    + len(previous_sentence)
                    + 1
                    <= overlap
                ):
                    overlap_sentences.insert(
                        0,
                        previous_sentence
                    )
                    overlap_length += (
                        len(previous_sentence) + 1
                    )
                else:
                    break

            current_sentences = overlap_sentences
            current_length = overlap_length

        current_sentences.append(sentence)
        current_length += sentence_length + 1

    # Add final chunk
    if current_sentences:
        chunks.append({
            "chunk_id": len(chunks) + 1,
            "text": " ".join(current_sentences),
            "metadata": metadata.copy() if metadata else {}
        })

    return chunks