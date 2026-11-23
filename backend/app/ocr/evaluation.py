"""Reference-based text recognition evaluation, separate from model confidence."""
import unicodedata

MAX_EVALUATION_CHARACTERS = 20_000


def _distance(a, b):
    """Exact Levenshtein distance using bit vectors (bounded memory, no dependency)."""
    if len(a) > len(b):
        a, b = b, a
    if not a:
        return len(b)
    masks = {}
    for i, value in enumerate(a):
        masks[value] = masks.get(value, 0) | (1 << i)
    mask = (1 << len(a)) - 1
    positive, negative, distance = mask, 0, len(a)
    high = 1 << (len(a) - 1)
    for value in b:
        equal = masks.get(value, 0)
        zero = (((equal & positive) + positive) ^ positive) | equal | negative
        hp = negative | ~(zero | positive)
        hn = positive & zero
        distance += bool(hp & high) - bool(hn & high)
        hp = (hp << 1) | 1
        hn <<= 1
        positive = (hn | ~(zero | hp)) & mask
        negative = zero & hp
    return distance


def normalize_text(text):
    # Ignore wrapping/spacing differences, retain case, spelling and punctuation.
    return ' '.join(unicodedata.normalize('NFKC', text).split())


def evaluate_text(prediction, reference):
    if len(prediction) > MAX_EVALUATION_CHARACTERS or len(reference) > MAX_EVALUATION_CHARACTERS:
        raise ValueError('Evaluate pages of up to 20,000 characters at a time.')
    prediction, reference = normalize_text(prediction), normalize_text(reference)
    if not reference:
        raise ValueError('Provide a non-empty correct reference transcription.')
    character_errors = _distance(prediction, reference)
    word_errors = _distance(prediction.split(), reference.split())
    return {
        'cer_percent': round(100 * character_errors / len(reference), 2),
        'wer_percent': round(100 * word_errors / len(reference.split()), 2),
        'character_errors': character_errors,
        'word_errors': word_errors,
        'reference_characters': len(reference),
        'reference_words': len(reference.split()),
        'exact_match': prediction == reference,
        'normalization': 'Unicode NFKC and collapsed whitespace; case and punctuation retained.',
    }
