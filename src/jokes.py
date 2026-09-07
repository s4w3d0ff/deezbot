import asyncio
import random
import weakref
import logging
import spacy

logger = logging.getLogger(__name__)

DEFAULT_SPACY_MODEL = 'en_core_web_sm'
_nlp = None
_spacy_model = None
_load_attempted = False
_load_locks = weakref.WeakKeyDictionary()


def configure_spacy(model):
    global _nlp, _spacy_model, _load_attempted
    name = model or DEFAULT_SPACY_MODEL
    if name == _spacy_model and _load_attempted:
        return
    _spacy_model = name
    _nlp = spacy.load(name)
    _load_attempted = True
    _load_locks.clear()


async def ensure_nlp():
    global _nlp
    if _nlp is not None:
        return _nlp
    loop = asyncio.get_running_loop()
    async with _load_locks.setdefault(loop, asyncio.Lock()):
        if _nlp is None:
            _nlp = await asyncio.to_thread(spacy.load, _spacy_model or DEFAULT_SPACY_MODEL)
    return _nlp


async def replace_random_noun_chunk(text, replacement="these walnuts"):
    """Uses spacy to find all noun 'chunks' <text>. Then replaces a random noun chunk with the <replacement>. Returns result as string"""
    doc = (await ensure_nlp())(text)
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
