"""Which scores stand out for a query, judged against their own video, and the ranges frames form.

There is no fixed minimum score. SigLIP's text-to-image cosines are low and bunched together,
and e5's are high and bunched together, and the same number means something different in every
video: a lecture's slides all look alike to the model, a travel video's frames do not. So a
frame, or a keyframe's text, is a hit when it stands out from *its own video's* scores -- its
z-score against every score of that video is at least the threshold -- and when even the best
one does not stand out, there is no hit at all rather than the least-bad ones. Without that, a
sub-agent handed "the closest frames" will find its answer in them whether it is there or not.

Frames have one more way to be a hit. Something on screen for most of the video -- "a padel
court", at 0.18 in every frame -- stands out nowhere, so a frame at or above a *present* level
is a hit whatever its z-score.

There is no similarity floor under the z-score, and that is on purpose. SigLIP scores within one
video are tightly bunched (a standard deviation around 0.005), so in a video where nothing
matches, some frames still stand out by chance: on a padel match, "a dog" found a frame at z 4.3
with a similarity of 0.03, where a real match scores 0.12 or more. That is still true, and a floor
(0.08) once dropped those. It was removed on purpose: the sub-agent looks at every moment it is
handed, and that look is the acceptance step, so the search favours catching a match over
precision.

Keyframe texts are few -- often a handful in a whole video -- and a z-score over so few scores
means little. Below a minimum count, the closest texts are taken with no z filter.
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


def z_scores(similarities: Sequence[float]) -> np.ndarray:
    """Each score's distance from the mean of all of them, in standard deviations.

    Scores that are all the same have no distribution to stand out from, so every one of them
    is at zero.
    """
    scores = np.asarray(similarities, dtype=np.float64)
    if scores.size == 0:
        return scores
    spread = float(scores.std())
    if spread == 0.0:
        return np.zeros_like(scores)
    return (scores - float(scores.mean())) / spread


def standout_frames(
    times: Sequence[float],
    similarities: Sequence[float],
    *,
    z_threshold: float,
    present_similarity: float,
) -> list[StandoutFrame]:
    """The frames that match the query, in the order given.

    A frame matches when its z-score against the whole video is at least `z_threshold`, or
    when its similarity alone reaches `present_similarity`. `times` and `similarities` are every
    sampled frame of one video, in the same order.
    """
    scores = np.asarray(similarities, dtype=np.float64)
    frame_z_scores = z_scores(scores)
    spread = float(scores.std()) if scores.size else 0.0
    return [
        StandoutFrame(time_seconds=float(time), similarity=float(score), z_score=float(z))
        for time, score, z in zip(times, scores, frame_z_scores)
        if (spread > 0.0 and z >= z_threshold) or score >= present_similarity
    ]


def standout_positions(
    similarities: Sequence[float],
    *,
    z_threshold: float,
    minimum_for_z_score: int,
) -> list[int]:
    """Which of these scores are hits, as positions into `similarities`, in the order given.

    With at least `minimum_for_z_score` scores, a hit is a score whose z-score is at least
    `z_threshold`. With fewer, every score is a hit, and the caller keeps the closest.
    """
    if len(similarities) < minimum_for_z_score:
        return list(range(len(similarities)))
    spread = float(np.asarray(similarities, dtype=np.float64).std())
    if spread == 0.0:
        return []
    return [
        position
        for position, z in enumerate(z_scores(similarities))
        if z >= z_threshold
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
