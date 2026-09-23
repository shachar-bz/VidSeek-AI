"""Divides a video's sampled frames into segments where the picture changes, and picks keyframes.

No shot-detection model is involved: the segments come out of the same 0.5 fps frames that
were embedded for search. Walking them in order, a frame is *changed* when it differs from the
current segment's first frame -- its reference -- in either of two ways:

* its image embedding is far enough from the reference's -- a cut, a new scene, a new view
  (`scene_change`);
* its perceptual hash is far enough from the reference's -- a new slide, new writing on a
  board, which the embedding can see as the same picture (`text_change`).

A frame opens a new segment only when the change is *confirmed*: it holds for
`change_hold_samples` consecutive frames, and the new picture is stable across them. The hold
is what stops a flash or someone walking through the shot from splitting anything. Stability
is what keeps the hash honest: on moving footage the hash of every sample differs from the
last by a third of its bits while the embedding barely moves, so a hash change counts only
when the new picture then stays put, the way a new slide does. It also puts the boundary in
the right place: the first frame of a dissolve is neither picture, is not stable, and the
boundary lands on the frame after it. A segment shorter than `min_segment_seconds` is merged
into its neighbour.

The boundary frame is the new segment's reference and its keyframe: the first frame after the
change that is known to be stable. A long segment, such as a board being written on slowly,
gets a further keyframe every `periodic_keyframe_seconds`, so what was added over a minute is
not represented only by the empty board it started as.

Every threshold here is a starting value. The eval set in VISUAL_UNDERSTANDING_PLAN.md §8 is
what tunes them, which is why they sit in `SegmentationSettings` rather than in the code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

import numpy as np

from .perceptual_hash import hash_distance

# What opened a segment. Must match `video_visual_segments_boundary_kind_known` in
# 0022_video_visual_index.sql.
VIDEO_START = "video_start"
SCENE_CHANGE = "scene_change"
TEXT_CHANGE = "text_change"


@dataclass(frozen=True)
class SegmentationSettings:
    """The thresholds content-change segmentation runs on."""

    # Cosine distance between SigLIP embeddings at or above which a frame shows a new scene.
    # Consecutive samples of one continuous shot sit around 0.01-0.02; a cut is 0.25 or more.
    scene_change_distance: float = 0.15

    # Differing pHash bits (out of 64) at or above which a frame shows new text or a new slide.
    text_change_bits: int = 12

    # At most this many differing bits between consecutive frames of a new picture for a hash
    # change to count: a static slide stays within a few bits, moving footage jumps 20 or more.
    stable_picture_bits: int = 6

    # How many consecutive changed frames it takes to open a segment.
    change_hold_samples: int = 2

    # A segment shorter than this is merged into its neighbour.
    min_segment_seconds: float = 6.0

    # How far apart a long segment's keyframes are.
    periodic_keyframe_seconds: float = 60.0


DEFAULT_SETTINGS = SegmentationSettings()


@dataclass(frozen=True)
class FrameSignature:
    """What segmentation needs of one sampled frame: when it was, and its two fingerprints."""

    time_seconds: float
    # L2-normalized, so a dot product is the cosine similarity.
    embedding: np.ndarray
    perceptual_hash: int


@dataclass(frozen=True)
class VisualSegment:
    """One stretch of the video whose picture stays the same."""

    index: int
    start_seconds: float
    end_seconds: float
    boundary_kind: str
    keyframe_times: tuple[float, ...]


@dataclass(frozen=True)
class _Span:
    """A segment while it is being built: frame positions rather than times."""

    first_frame: int
    boundary_kind: str
    # The frame everything after the boundary is compared against, and the segment's keyframe.
    reference_frame: int
    # One past the last frame; filled in once the next segment's start is known.
    end_frame: int = -1


def divide_into_segments(
    frames: Sequence[FrameSignature],
    *,
    interval_seconds: float,
    duration_seconds: float | None = None,
    settings: SegmentationSettings = DEFAULT_SETTINGS,
) -> list[VisualSegment]:
    """Segments covering the whole video, earliest first, each with its keyframe times.

    The segments partition the video: the first starts at zero, each one ends where the next
    begins, and the last ends at `duration_seconds` -- or one sampling interval after the last
    frame, when the duration is unknown or ended before it.
    """
    if not frames:
        return []
    end_of_video = _end_of_video(frames, interval_seconds, duration_seconds)
    spans = _merge_short_spans(_spans_at_changes(frames, settings), frames, end_of_video, settings)
    segments = []
    for index, span in enumerate(spans):
        start = 0.0 if index == 0 else frames[span.first_frame].time_seconds
        end = end_of_video if span.end_frame >= len(frames) else frames[span.end_frame].time_seconds
        segments.append(
            VisualSegment(
                index=index,
                start_seconds=start,
                end_seconds=end,
                boundary_kind=VIDEO_START if index == 0 else span.boundary_kind,
                keyframe_times=_keyframe_times(frames, span, settings),
            )
        )
    return segments


def _spans_at_changes(
    frames: Sequence[FrameSignature], settings: SegmentationSettings
) -> list[_Span]:
    """The first pass: a new span at every frame where a change is confirmed."""
    spans = [_Span(first_frame=0, boundary_kind=VIDEO_START, reference_frame=0)]
    for position in range(1, len(frames)):
        kind = _confirmed_change(frames, spans[-1].reference_frame, position, settings)
        if kind is None:
            continue
        spans[-1] = replace(spans[-1], end_frame=position)
        spans.append(_Span(first_frame=position, boundary_kind=kind, reference_frame=position))
    spans[-1] = replace(spans[-1], end_frame=len(frames))
    return spans


def _confirmed_change(
    frames: Sequence[FrameSignature],
    reference: int,
    position: int,
    settings: SegmentationSettings,
) -> str | None:
    """Whether a new segment opens at `position`, and what kind of change opens it.

    The frames from `position` on, `change_hold_samples` of them, must all differ from the
    reference in the same way and agree with each other. A video's last frames cannot be
    confirmed, since there is nothing after them to hold the change.
    """
    run = frames[position : position + settings.change_hold_samples]
    if len(run) < settings.change_hold_samples:
        return None
    anchor = frames[reference]
    if all(_embedding_distance(anchor, frame) >= settings.scene_change_distance for frame in run) and all(
        _embedding_distance(first, second) < settings.scene_change_distance
        for first, second in pairwise(run)
    ):
        return SCENE_CHANGE
    if all(
        hash_distance(anchor.perceptual_hash, frame.perceptual_hash) >= settings.text_change_bits
        for frame in run
    ) and all(
        hash_distance(first.perceptual_hash, second.perceptual_hash) <= settings.stable_picture_bits
        for first, second in pairwise(run)
    ):
        return TEXT_CHANGE
    return None


def _embedding_distance(first: FrameSignature, second: FrameSignature) -> float:
    return 1.0 - float(np.dot(first.embedding, second.embedding))


def _merge_short_spans(
    spans: list[_Span],
    frames: Sequence[FrameSignature],
    end_of_video: float,
    settings: SegmentationSettings,
) -> list[_Span]:
    """The second pass: fold every span shorter than the minimum into a neighbour.

    A short span joins the one before it, which keeps its own boundary and keyframe: the
    short stretch was not on screen long enough to stand for anything. The first span has no
    span before it, so when it is the short one, the span after it is folded in instead and
    that span's keyframe represents both.
    """

    def length(span: _Span) -> float:
        end = end_of_video if span.end_frame >= len(frames) else frames[span.end_frame].time_seconds
        return end - frames[span.first_frame].time_seconds

    merged: list[_Span] = []
    for span in spans:
        if merged and length(span) < settings.min_segment_seconds:
            merged[-1] = replace(merged[-1], end_frame=span.end_frame)
        else:
            merged.append(span)
    if len(merged) > 1 and length(merged[0]) < settings.min_segment_seconds:
        following = merged.pop(1)
        merged[0] = replace(
            merged[0], end_frame=following.end_frame, reference_frame=following.reference_frame
        )
    return merged


def _keyframe_times(
    frames: Sequence[FrameSignature], span: _Span, settings: SegmentationSettings
) -> tuple[float, ...]:
    """The span's reference frame, then one frame every `periodic_keyframe_seconds` after it."""
    times = [frames[span.reference_frame].time_seconds]
    for position in range(span.reference_frame + 1, span.end_frame):
        if frames[position].time_seconds - times[-1] >= settings.periodic_keyframe_seconds:
            times.append(frames[position].time_seconds)
    return tuple(times)


def _end_of_video(
    frames: Sequence[FrameSignature], interval_seconds: float, duration_seconds: float | None
) -> float:
    """Where the last segment ends: the video's duration, if it is known and not too short."""
    if duration_seconds is not None and duration_seconds > frames[-1].time_seconds:
        return duration_seconds
    return frames[-1].time_seconds + interval_seconds
