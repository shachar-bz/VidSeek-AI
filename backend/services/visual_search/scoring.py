"""Which frames stand out for a query, judged against their own video, and the ranges they form.

There is no fixed minimum score. SigLIP's text-to-image cosines are low and bunched together,
and the same number means something different in every video: a lecture's slides all look
alike to the model, a travel video's frames do not. So a frame is a hit when it stands out from
*its own video's* scores -- its z-score against every sampled frame of that video is at least
`z_threshold` -- and when even the best frame does not stand out, there is no hit at all rather
than the least-bad frames. Without that, a sub-agent handed "the closest frames" will find its
answer in them whether it is there or not.

Two absolute levels on the raw similarity complete the rule, because a z-score alone fails at
both ends. SigLIP scores within one video are tightly bunched (a standard deviation around
0.005), so in a video where nothing matches, some frames still stand out by chance: on a padel
match, "a dog" found a frame at z 4.3 with a similarity of 0.03, where a real match scores 0.12
or more. A low floor drops those. And something on screen the whole time -- "a padel court", at
0.18 in every frame -- stands out nowhere, so a frame at or above a *present* level is a hit
whatever its z-score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StandoutFrame:
    """One frame that stood out for the query."""

    time_seconds: float
    similarity: float
    z_score: float


@dataclass(frozen=True)
class HitRange:
    """Consecutive standout frames, merged into one stretch of the video."""

    start_seconds: float
    end_seconds: float
    # The best frame in the range: how far it stood out, and when it was.
    peak_z_score: float
    peak_time_seconds: float


def standout_frames(
    times: Sequence[float],
    similarities: Sequence[float],
    *,
    z_threshold: float,
    similarity_floor: float,
    present_similarity: float,
) -> list[StandoutFrame]:
    """The frames that match the query, in time order.

    A frame matches when it stands out from the whole video -- z-score at least
    `z_threshold` and similarity at least `similarity_floor` -- or when its similarity alone
    reaches `present_similarity`. `times` and `similarities` are every sampled frame of one
    video, in the same order. A video whose frames all score the same has no distribution to
    stand out from, so only the present level can find anything in it.
    """
    scores = np.asarray(similarities, dtype=np.float64)
    if scores.size == 0:
        return []
    spread = float(scores.std())
    z_scores = (
        (scores - float(scores.mean())) / spread if spread > 0.0 else np.zeros_like(scores)
    )
    return [
        StandoutFrame(time_seconds=float(time), similarity=float(score), z_score=float(z))
        for time, score, z in zip(times, scores, z_scores)
        if (spread > 0.0 and z >= z_threshold and score >= similarity_floor)
        or score >= present_similarity
    ]


def merge_into_ranges(
    frames: Sequence[StandoutFrame], *, interval_seconds: float
) -> list[HitRange]:
    """Consecutive standout frames joined into ranges, in time order.

    Two frames are consecutive when no sample lies between them. A range runs from its first
    frame to its last, so a single frame is a range of zero length: that is what was actually
    observed, and the sub-agent can look either side of it.
    """
    ranges: list[HitRange] = []
    for frame in sorted(frames, key=lambda item: item.time_seconds):
        previous = ranges[-1] if ranges else None
        if previous is not None and frame.time_seconds - previous.end_seconds <= interval_seconds * 1.5:
            peak_is_new = frame.z_score > previous.peak_z_score
            ranges[-1] = HitRange(
                start_seconds=previous.start_seconds,
                end_seconds=frame.time_seconds,
                peak_z_score=frame.z_score if peak_is_new else previous.peak_z_score,
                peak_time_seconds=frame.time_seconds if peak_is_new else previous.peak_time_seconds,
            )
        else:
            ranges.append(
                HitRange(
                    start_seconds=frame.time_seconds,
                    end_seconds=frame.time_seconds,
                    peak_z_score=frame.z_score,
                    peak_time_seconds=frame.time_seconds,
                )
            )
    return ranges
