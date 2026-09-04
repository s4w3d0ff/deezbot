import random
import logging
import spacy

logger = logging.getLogger(__name__)

DEFAULT_SPACY_MODEL = 'en_core_web_sm'
_nlp = None
_spacy_model = None


def configure_spacy(model):
    global _nlp, _spacy_model
    if model != _spacy_model:
        _spacy_model = model or DEFAULT_SPACY_MODEL
        _nlp = None


def get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load(_spacy_model or DEFAULT_SPACY_MODEL)
    return _nlp


def replace_random_noun_chunk(text, replacement="these walnuts"):
    """Uses spacy to find all noun 'chunks' <text>. Then replaces a random noun chunk with the <replacement>. Returns result as string"""
    doc = get_nlp()(text)
    noun_chunks = list(doc.noun_chunks)
    if not noun_chunks:
        return None

    if len(noun_chunks) > 1:
        del noun_chunks[0]

    to_replace = random.choice(noun_chunks)
    start = to_replace.start_char
    end = to_replace.end_char
    out = text[:start] + replacement + text[end:]

    if out.strip() == replacement.strip():
        return None

    logger.debug(f"[replace_random_noun_chunk] {text} -> {out}")
    return out
