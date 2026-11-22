"""Tests for BM25 scoring of one video's memories against a query."""

import math

import pytest

from backend.services.lexical_search import bm25_scores


def test_document_with_the_exact_term_ranks_first():
    documents = [["the", "cat", "sat"], ["the", "dog", "ran"], ["a", "bird", "flew"]]
    scores = bm25_scores(["dog"], documents)
    assert scores[1] > 0
    assert scores[0] == scores[2] == 0.0


def test_term_in_every_document_weighs_little():
    documents = [["python", "numpy"], ["python", "pandas"], ["python", "flask"], ["python", "django"]]
    common = bm25_scores(["python"], documents)
    rare = bm25_scores(["numpy"], documents)
    assert rare[0] > 5 * common[0]
    # IDF for a term in all N documents is ln(1 + 0.5 / (N + 0.5)), small but positive.
    assert common[0] > 0


def test_rare_term_outweighs_common_term():
    documents = [["python", "numpy"], ["python", "python"], ["python", "flask"]]
    scores = bm25_scores(["python", "numpy"], documents)
    assert scores.index(max(scores)) == 0


def test_shorter_document_wins_for_the_same_term_frequency():
    documents = [["numpy", "talk"], ["numpy"] + ["filler"] * 20, ["other", "words"]]
    scores = bm25_scores(["numpy"], documents)
    assert scores[0] > scores[1] > 0


def test_b_zero_disables_length_normalization():
    documents = [["numpy", "talk"], ["numpy"] + ["filler"] * 20, ["other"]]
    scores = bm25_scores(["numpy"], documents, b=0.0)
    assert scores[0] == pytest.approx(scores[1])


def test_repeated_query_term_counts_once():
    documents = [["numpy", "talk"], ["other"]]
    assert bm25_scores(["numpy", "numpy"], documents) == bm25_scores(["numpy"], documents)


def test_known_single_term_value():
    documents = [["a", "b"], ["c", "d"]]
    # N=2, n=1: idf = ln(1 + 1.5/1.5) = ln 2; tf=1, |d| = avgdl, so the tf part is 1.
    assert bm25_scores(["a"], documents)[0] == pytest.approx(math.log(2))


def test_empty_inputs_score_zero_without_errors():
    assert bm25_scores(["a"], []) == []
    assert bm25_scores([], [["a"], ["b"]]) == [0.0, 0.0]
    assert bm25_scores(["a"], [[], []]) == [0.0, 0.0]
    assert bm25_scores(["a"], [[], ["a"]])[0] == 0.0
    assert bm25_scores(["a"], [[], ["a"]])[1] > 0
