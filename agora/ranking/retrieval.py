"""Out-of-network retrieval: a two-tower-lite stand-in for Phoenix retrieval.

Item tower: the offer's hashed-feature embedding from Phoenix-lite's shared table
plus a hashed bag-of-words content vector. User tower: the action-weighted mean
of the items in the viewer's history plus the content vectors of the viewer's
active intents. Score = cosine on both, blended. Production Phoenix retrieval
trains the two towers jointly (phoenix/xrex/models/recsys_two_tower_model.py);
here the item tower is learned only through the ranker it shares tables with.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

_WORD = re.compile(r"[a-z0-9]+|[一-鿿]")
TEXT_DIM = 512
ACTION_STRENGTH = {"purchase": 3.0, "repost": 2.0, "favorite": 1.5, "follow_author": 1.5, "inquire": 1.5,
                   "reply": 1.2, "share": 1.2, "click": 0.5, "dwell": 0.3}
_bucket_cache: dict[str, int] = {}


def _bucket(word: str) -> int:
    b = _bucket_cache.get(word)
    if b is None:
        b = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest(), "little") % TEXT_DIM
        _bucket_cache[word] = b
    return b


def text_vector(text: str) -> np.ndarray:
    v = np.zeros(TEXT_DIM)
    words = _WORD.findall(text.lower())
    for w in words:
        v[_bucket(w)] += 1.0
    for a, b in zip(words, words[1:]):  # bigrams catch short CJK phrases
        v[_bucket(a + "_" + b)] += 0.5
    np.log1p(v, out=v)
    n = np.linalg.norm(v)
    return v / n if n else v


def offer_text(offer: dict) -> str:
    return " ".join([offer.get("title", ""), offer.get("description", ""), offer.get("category", ""),
                     " ".join(offer.get("tags", []))])


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def user_vectors(model, history: list[tuple[list[str], str]], intents_text: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """history: [(item_tokens, action)] -> (embedding-space vector, text-space vector)."""
    emb = np.zeros(model.d)
    for toks, action in history:
        emb += ACTION_STRENGTH.get(action, 0.0) * model.item_vector(toks)
    txt = np.zeros(TEXT_DIM)
    for t in intents_text:
        txt += text_vector(t)
    return _unit(emb), _unit(txt)


def retrieve(model, user_emb: np.ndarray, user_txt: np.ndarray, corpus: list[tuple[str, list[str], np.ndarray]],
             k: int, alpha: float = 0.5) -> list[tuple[str, float]]:
    """corpus: [(offer_id, item_tokens, text_vec)] -> top-k (offer_id, score)."""
    if not corpus:
        return []
    scores = []
    for oid, toks, tv in corpus:
        e = _unit(model.item_vector(toks))
        scores.append((oid, alpha * float(e @ user_emb) + (1 - alpha) * float(tv @ user_txt)))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:k]
