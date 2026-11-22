"""`bm25_scores`: Okapi BM25 over one video's memories, with IDF taken from those memories alone.

The corpus is deliberately tiny -- one video, nine to forty-odd memories -- and that is the
point: a word is rare or common *in this video*. A speaker who says "Python" in every passage
of a Python talk gives the word almost no weight, while the one passage that names a library
stands out. A global IDF would know nothing about that.

IDF is the "plus one" form, ln(1 + (N - n + 0.5) / (n + 0.5)), which is never negative. The
classic form goes below zero for a term in more than half the documents, and in a corpus this
small that happens to ordinary topic words, which would then push matching memories *below*
ones that do not mention the word at all.

Each distinct query term counts once, so repeating a word in the query does not multiply it.
Term frequency in the memory saturates through k1 and is normalized by the memory's length
through b, so a long passage that mentions a word once does not beat a short one that is about
it. Empty inputs score zero instead of failing, since a video with no speech, or a query of
pure punctuation, is a normal case for the caller.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

# How quickly repeating a term in a memory stops adding to its score.
DEFAULT_K1 = 1.2
# How strongly a memory's length relative to the average discounts its term frequencies.
DEFAULT_B = 0.75


def bm25_scores(
    query_tokens: Sequence[str],
    document_tokens: Sequence[Sequence[str]],
    *,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> list[float]:
    """One BM25 score per document, in input order; 0.0 for a document sharing no query term."""
    document_count = len(document_tokens)
    query_terms = list(dict.fromkeys(query_tokens))
    if document_count == 0:
        return []
    if not query_terms:
        return [0.0] * document_count

    term_frequencies = [Counter(tokens) for tokens in document_tokens]
    document_lengths = [len(tokens) for tokens in document_tokens]
    average_length = sum(document_lengths) / document_count
    term_idf = {
        term: _idf(document_count, sum(1 for frequencies in term_frequencies if term in frequencies))
        for term in query_terms
    }

    scores: list[float] = []
    for frequencies, length in zip(term_frequencies, document_lengths):
        # With every document empty there is nothing to normalize against; no term can match.
        length_ratio = length / average_length if average_length > 0 else 0.0
        length_norm = k1 * (1.0 - b + b * length_ratio)
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if frequency:
                score += term_idf[term] * frequency * (k1 + 1.0) / (frequency + length_norm)
        scores.append(score)
    return scores


def _idf(document_count: int, documents_with_term: int) -> float:
    """How rare a term is in this corpus; never negative, near zero for a term in every document."""
    return math.log(1.0 + (document_count - documents_with_term + 0.5) / (documents_with_term + 0.5))
