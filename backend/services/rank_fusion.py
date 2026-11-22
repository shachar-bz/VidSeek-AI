"""`reciprocal_rank_fusion`: one ranking out of several, by where each item placed in each.

Hybrid memory search has two rankings of the same memories -- e5 cosine and BM25 -- whose
scores cannot be compared: a cosine of 0.86 and a BM25 of 7.3 are on unrelated scales, and both
scales shift from video to video. Reciprocal rank fusion ignores the scores and uses only the
ranks: an item at rank r in a ranking earns 1 / (k + r) from it, rank starting at 1, and its
fused score is the sum over all rankings. Something near the top of either list rises; something
near the top of both rises furthest.

k damps how much the very first places dominate. 60 is the value from the original paper
(Cormack, Clarke and Buettcher, 2009) and is used nearly everywhere; with it a first place is
worth 1/61 and a fortieth 1/100, so no single list's top spot can outvote broad agreement.

The rankings weigh equally. An item missing from a ranking gets nothing from it, which is how a
memory BM25 never matched (no shared word) still competes on meaning alone. If an id appears
twice in one ranking, only its first (best) place counts.

Equal fused scores are ordered by first appearance: the order in which ids are first met when
reading the first ranking top to bottom, then the second, and so on. That makes the result
deterministic, and it lets the caller decide which ranking wins ties by the order it passes them.
"""

from __future__ import annotations

from collections.abc import Sequence

# The rank offset from the original RRF paper.
DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, k: int = DEFAULT_RRF_K
) -> list[tuple[str, float]]:
    """Every id from `rankings` with its fused score, highest first, ties by first appearance.

    Each ranking lists ids best first.
    """
    fused_scores: dict[str, float] = {}
    for ranking in rankings:
        seen_in_this_ranking: set[str] = set()
        for rank, item_id in enumerate(ranking, start=1):
            if item_id in seen_in_this_ranking:
                continue
            seen_in_this_ranking.add(item_id)
            fused_scores[item_id] = fused_scores.get(item_id, 0.0) + 1.0 / (k + rank)
    # dict keeps first-appearance order and sorted() is stable, so ties keep that order.
    return sorted(fused_scores.items(), key=lambda id_and_score: -id_and_score[1])
