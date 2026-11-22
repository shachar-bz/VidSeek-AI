"""Public interface of lexical search: matching a video's memories by the words they share.

`tokenize` turns Hebrew or English text into the terms a search compares, the same way for a
query and for a memory; `bm25_scores` scores every memory of one video against a query's terms.
Neither needs a model or a database, so they sit beside the e5 search as its exact-word half:
e5 finds speech that means the same thing, BM25 finds speech that says the same rare word -- a
name, a number, a term e5 blurs into its neighbours.
"""

from .bm25 import DEFAULT_B, DEFAULT_K1, bm25_scores
from .hebrew_english_tokenizer import HEBREW_PREFIX_LETTERS, tokenize

__all__ = [
    "DEFAULT_B",
    "DEFAULT_K1",
    "HEBREW_PREFIX_LETTERS",
    "bm25_scores",
    "tokenize",
]
