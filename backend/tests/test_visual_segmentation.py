"""Tests for content-change segmentation: where segments open, what opens them, and keyframes.

Frames are built by hand rather than decoded, so each test states exactly how the picture
changes: an embedding direction stands for a scene, a hash for the layout of what is on it.
"""

import numpy as np
from PIL import Image, ImageDraw

from backend.services.visual_indexing.segments import (
    SCENE_CHANGE,
    TEXT_CHANGE,
    VIDEO_START,
    FrameSignature,
    SegmentationSettings,
    divide_into_segments,
    hash_distance,
    perceptual_hash,
)

INTERVAL = 2.0
SLIDE_A = 0
SLIDE_B = (1 << 64) - 1  # every bit different from SLIDE_A


def scene(index: int, drift: float = 0.0) -> np.ndarray:
    """A unit vector for scene `index`; `drift` tilts it slightly, as motion inside a shot does."""
    vector = np.zeros(16)
    vector[index] = 1.0
    vector[15] = drift
    return vector / np.linalg.norm(vector)


def frames(*pictures: tuple[np.ndarray, int]) -> list[FrameSignature]:
    return [
        FrameSignature(time_seconds=position * INTERVAL, embedding=embedding, perceptual_hash=hashed)
        for position, (embedding, hashed) in enumerate(pictures)
    ]


def spans(segments) -> list[tuple[float, float, str]]:
    return [(s.start_seconds, s.end_seconds, s.boundary_kind) for s in segments]


def test_a_cut_opens_a_scene_change_segment_at_the_first_frame_after_it() -> None:
    video = frames(*[(scene(0), SLIDE_A)] * 5, *[(scene(1), SLIDE_A)] * 5)

    segments = divide_into_segments(video, interval_seconds=INTERVAL, duration_seconds=20.0)

    assert spans(segments) == [(0.0, 10.0, VIDEO_START), (10.0, 20.0, SCENE_CHANGE)]
    assert segments[1].keyframe_times == (10.0,)


def test_a_new_slide_the_embedding_cannot_see_opens_a_text_change_segment() -> None:
    # Two slides look alike to SigLIP; only the perceptual hash tells them apart.
    video = frames(*[(scene(0), SLIDE_A)] * 5, *[(scene(0), SLIDE_B)] * 5)

    segments = divide_into_segments(video, interval_seconds=INTERVAL, duration_seconds=20.0)

    assert spans(segments) == [(0.0, 10.0, VIDEO_START), (10.0, 20.0, TEXT_CHANGE)]


def test_a_one_sample_flash_does_not_split_anything() -> None:
    video = frames(
        *[(scene(0), SLIDE_A)] * 4, (scene(1), SLIDE_B), *[(scene(0), SLIDE_A)] * 5
    )

    segments = divide_into_segments(video, interval_seconds=INTERVAL)

    assert spans(segments) == [(0.0, 20.0, VIDEO_START)]


def test_moving_footage_with_an_unstable_hash_is_not_a_text_change() -> None:
    # On moving footage the hash of every sample differs from the last by a third of its
    # bits while the embedding barely moves; a new slide, by contrast, then stays put.
    rng = np.random.default_rng(7)
    moving = [(scene(0, drift=0.01 * position), int(rng.integers(0, 2**63))) for position in range(15)]

    segments = divide_into_segments(frames(*moving), interval_seconds=INTERVAL)

    assert spans(segments) == [(0.0, 30.0, VIDEO_START)]


def test_a_dissolve_puts_the_boundary_on_the_first_stable_frame_of_the_new_scene() -> None:
    blend = scene(0) + scene(1)
    blend /= np.linalg.norm(blend)
    video = frames(
        *[(scene(0), SLIDE_A)] * 5, (blend, SLIDE_A), *[(scene(1), SLIDE_A)] * 5
    )

    segments = divide_into_segments(video, interval_seconds=INTERVAL)

    assert [s.start_seconds for s in segments] == [0.0, 12.0]


def test_a_shot_shorter_than_the_minimum_is_folded_into_the_one_before_it() -> None:
    video = frames(
        *[(scene(0), SLIDE_A)] * 5, *[(scene(1), SLIDE_A)] * 2, *[(scene(2), SLIDE_A)] * 5
    )

    segments = divide_into_segments(video, interval_seconds=INTERVAL, duration_seconds=24.0)

    assert spans(segments) == [(0.0, 14.0, VIDEO_START), (14.0, 24.0, SCENE_CHANGE)]
    assert segments[0].keyframe_times == (0.0,)


def test_a_short_opening_is_folded_into_the_segment_after_it() -> None:
    video = frames(*[(scene(0), SLIDE_A)] * 2, *[(scene(1), SLIDE_A)] * 8)

    segments = divide_into_segments(video, interval_seconds=INTERVAL, duration_seconds=20.0)

    assert spans(segments) == [(0.0, 20.0, VIDEO_START)]
    # The opening was not on screen long enough to stand for the segment; what followed is.
    assert segments[0].keyframe_times == (4.0,)


def test_segments_partition_the_video_up_to_its_duration() -> None:
    video = frames(*[(scene(0), SLIDE_A)] * 5, *[(scene(1), SLIDE_A)] * 5)

    with_duration = divide_into_segments(video, interval_seconds=INTERVAL, duration_seconds=21.3)
    without = divide_into_segments(video, interval_seconds=INTERVAL)

    assert with_duration[-1].end_seconds == 21.3
    assert without[-1].end_seconds == 20.0
    assert all(a.end_seconds == b.start_seconds for a, b in zip(with_duration, with_duration[1:]))
    assert [s.index for s in with_duration] == [0, 1]


def test_a_long_static_segment_gets_a_keyframe_every_minute() -> None:
    video = frames(*[(scene(0), SLIDE_A)] * 90)  # three minutes of one board

    segments = divide_into_segments(video, interval_seconds=INTERVAL)

    assert segments[0].keyframe_times == (0.0, 60.0, 120.0)


def test_the_thresholds_are_settings_not_constants() -> None:
    video = frames(*[(scene(0), SLIDE_A)] * 5, *[(scene(1), SLIDE_A)] * 5)

    segments = divide_into_segments(
        video,
        interval_seconds=INTERVAL,
        settings=SegmentationSettings(scene_change_distance=1.5),
    )

    assert len(segments) == 1


def test_no_frames_means_no_segments() -> None:
    assert divide_into_segments([], interval_seconds=INTERVAL) == []


def test_the_perceptual_hash_tells_two_slides_apart_and_ignores_a_little_noise() -> None:
    first = Image.new("RGB", (384, 216), "white")
    ImageDraw.Draw(first).rectangle((20, 20, 360, 50), fill="black")
    second = Image.new("RGB", (384, 216), "white")
    ImageDraw.Draw(second).rectangle((200, 70, 360, 200), fill="black")
    noisy = Image.fromarray(
        np.clip(
            np.asarray(first, dtype=np.int16) + np.random.default_rng(1).integers(-8, 8, (216, 384, 3)),
            0,
            255,
        ).astype(np.uint8)
    )

    assert hash_distance(perceptual_hash(first), perceptual_hash(noisy)) <= 6
    assert hash_distance(perceptual_hash(first), perceptual_hash(second)) >= 12
