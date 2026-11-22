"""Tests for fusing several rankings of the same ids with reciprocal rank fusion."""

import pytest

from backend.services.rank_fusion import reciprocal_rank_fusion


def test_known_numeric_example():
    fused = dict(reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]], k=60))
    assert fused["a"] == pytest.approx(1 / 61 + 1 / 63)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 63 + 1 / 62)


def test_sorted_by_fused_score_descending():
    ids = [item_id for item_id, _ in reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]])]
    assert ids == ["b", "a", "c"]


def test_id_absent_from_a_ranking_gets_nothing_from_it():
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["c"]], k=10))
    assert fused == pytest.approx({"a": 1 / 11, "b": 1 / 12, "c": 1 / 11})


def test_ties_broken_by_first_appearance():
    # "a" and "c" both score 1/61; "a" is met first, in the first ranking.
    assert [item_id for item_id, _ in reciprocal_rank_fusion([["a"], ["c"]])] == ["a", "c"]
    assert [item_id for item_id, _ in reciprocal_rank_fusion([["c"], ["a"]])] == ["c", "a"]
    # Mirrored lists tie everything; first ranking's order decides.
    assert [i for i, _ in reciprocal_rank_fusion([["x", "y"], ["y", "x"]])] == ["x", "y"]


def test_duplicate_id_in_one_ranking_counts_its_best_place_only():
    assert dict(reciprocal_rank_fusion([["a", "a"]], k=0)) == {"a": 1.0}


def test_empty_rankings():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
