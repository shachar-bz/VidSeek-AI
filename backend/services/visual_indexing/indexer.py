"""Builds one video's visual index from its local file: frame vectors, segments and keyframes.

The whole of ingestion's image work happens here, in one pass over the video:

    ffmpeg, 1 frame / 2 s  ->  SigLIP 2 embedding  -+->  frame vectors (the search layer)
                           ->  perceptual hash     -+->  segments + keyframe times (the map)

Frames are processed in batches and dropped as soon as their embedding and hash exist, so an
hour of video never holds more than one batch of images in memory. Nothing here touches the
database: the result is handed back whole, and the pipeline stage that called this decides
where it goes.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .sampling import SAMPLE_INTERVAL_SECONDS, SampledFrame, sample_frames
from .segments import (
    DEFAULT_SETTINGS,
    FrameSignature,
    SegmentationSettings,
    VisualSegment,
    divide_into_segments,
    perceptual_hash,
)

# How many sampled frames are embedded in one call. The encoder batches again internally;
# this only bounds how many decoded images are alive at once.
FRAMES_PER_BATCH = 64

logger = logging.getLogger(__name__)


class NoFramesToIndex(RuntimeError):
    """The video decoded to no frames at all, so there is nothing to index."""


@dataclass(frozen=True)
class IndexedFrame:
    """One sampled frame's time and its normalized image vector."""

    time_seconds: float
    embedding: np.ndarray


@dataclass(frozen=True)
class BuiltVisualIndex:
    """Everything indexing produced for one video, ready to be stored."""

    frames: tuple[IndexedFrame, ...]
    segments: tuple[VisualSegment, ...]
    elapsed_seconds: float


def visual_index_version(image_model_name: str, interval_seconds: float) -> str:
    """The label stored beside an index: which image model built it, at what sampling rate.

    Two indexes with different labels hold vectors that cannot be compared, which is the
    whole purpose of recording it: search refuses an index whose label is not the current one.
    """
    model = image_model_name.rsplit("/", 1)[-1]
    return f"{model}@{1 / interval_seconds:g}fps"


def build_visual_index(
    video_path: Path,
    *,
    duration_seconds: float | None = None,
    embed_images: Callable | None = None,
    interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
    settings: SegmentationSettings = DEFAULT_SETTINGS,
    stop_event: threading.Event | None = None,
) -> BuiltVisualIndex:
    """Sample, embed, hash and segment one video file.

    `embed_images` turns a list of PIL images into a `(n, 768)` array of normalized vectors;
    it defaults to the shared SigLIP 2 encoder, which is loaded when the first batch of frames
    is ready -- so a file ffmpeg cannot decode fails without loading a model at all. Raises
    `NoFramesToIndex` for a file that yields no frames, and lets the sampler's
    `SamplingStopped` and `FrameSamplingError` through.
    """
    started = time.perf_counter()
    frames: list[IndexedFrame] = []
    signatures: list[FrameSignature] = []
    batch: list[SampledFrame] = []
    encoder = embed_images

    def flush() -> None:
        nonlocal encoder
        if encoder is None:
            # Imported here so that importing this module does not load torch and
            # transformers, which a caller that only wants `visual_index_version` has no use for.
            from backend.services.embeddings.image_embedding import shared_encoder

            encoder = shared_encoder().embed_images
        vectors = encoder([sampled.image for sampled in batch])
        for sampled, vector in zip(batch, vectors):
            frames.append(IndexedFrame(time_seconds=sampled.time_seconds, embedding=vector))
            signatures.append(
                FrameSignature(
                    time_seconds=sampled.time_seconds,
                    embedding=vector,
                    perceptual_hash=perceptual_hash(sampled.image),
                )
            )
        batch.clear()

    for sampled in sample_frames(
        video_path, interval_seconds=interval_seconds, stop_event=stop_event
    ):
        batch.append(sampled)
        if len(batch) >= FRAMES_PER_BATCH:
            flush()
    if batch:
        flush()

    if not frames:
        raise NoFramesToIndex(f"{video_path.name} decoded to no frames")

    segments = divide_into_segments(
        signatures,
        interval_seconds=interval_seconds,
        duration_seconds=duration_seconds,
        settings=settings,
    )
    elapsed = time.perf_counter() - started
    logger.info(
        "Indexed %s visually: %d frames, %d segments in %.1f s",
        video_path.name,
        len(frames),
        len(segments),
        elapsed,
    )
    return BuiltVisualIndex(
        frames=tuple(frames), segments=tuple(segments), elapsed_seconds=elapsed
    )
