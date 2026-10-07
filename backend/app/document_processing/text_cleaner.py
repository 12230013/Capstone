import re

def clean_text(text: str) -> str:
    """
    Clean extracted document text.
    """

    if not isinstance(text, str):
        raise ValueError("Text must be a string.")

    # Replace multiple spaces/tabs with a single space
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    # Remove spaces at the beginning and end of lines
    text = "\n".join(
        line.strip()
        for line in text.splitlines()
    )

    # Remove leading/trailing whitespace
    text = text.strip()

    return text