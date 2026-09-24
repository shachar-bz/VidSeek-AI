"""Reciprocal rank fusion: several ranked lists combined using nothing but their ranks.

Each source the visual search reads scores on its own scale -- SigLIP cosines are low, e5's
bunch up high, MiniLM's sit in between -- so their scores cannot be added or compared. Their
ranks can. An item's fused score is the sum, over every list it appears in, of
`1 / (k + rank)`; an item near the top of two lists beats one at the top of only one.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass

# The usual constant. It damps how much the very first place is worth over the next few,
# so one list's favourite cannot outvote agreement between the others.
RRF_K = 60


@dataclass(frozen=True)
class FusedItem:
    """One item's fused score, and which lists it was found in."""

    key: Hashable
    score: float
    sources: tuple[str, ...]


def reciprocal_rank_fusion(
    rankings: Mapping[str, Mapping[Hashable, int]], *, k: int = RRF_K
) -> list[FusedItem]:
    """Every item in any list, best fused score first.

    `rankings` maps a source's name to each item's rank in that source, 1 being the best.
    Items may share a rank -- one transcript memory spans several segments, and each of them
    is found by it equally. Ties in the fused score keep the order items were first seen in,
    which follows the order of `rankings` and of each source's items.
    """
    scores: dict[Hashable, float] = {}
    sources: dict[Hashable, list[str]] = {}
    for source, ranks in rankings.items():
        for item, rank in ranks.items():
            if rank < 1:
                raise ValueError(f"{source} ranks {item!r} at {rank}; ranks start at 1")
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            sources.setdefault(item, []).append(source)
    ordered = sorted(scores, key=lambda item: scores[item], reverse=True)
    return [
        FusedItem(key=item, score=scores[item], sources=tuple(sources[item])) for item in ordered
    ]
