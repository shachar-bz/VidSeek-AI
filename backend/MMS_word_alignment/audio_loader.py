"""Decodes any audio or video file into the sample format the MMS aligner expects.

The aligner works on 16 kHz mono float32 samples, and ffmpeg can produce those from a
video file directly, so alignment never needs an intermediate audio file on disk.

This package is deliberately standalone and shares no code with
`backend/OpenAI_transcription`, which extracts audio for its own purposes, so that either
of the two can be deleted without touching the other.

Requires the ffmpeg binary on PATH.
"""

import os

import ffmpeg
import numpy as np

# The sample rate every MMS model is trained at. Resampling is left to ffmpeg, which does
# it while decoding, so no separate resampling step is needed.
SAMPLE_RATE_HZ = 16000
CHANNEL_COUNT = 1

# Raw 32-bit little-endian floats: the same layout as a numpy float32 array, so the
# decoded bytes can be reinterpreted without copying or converting them.
RAW_SAMPLE_FORMAT = "f32le"


def load_samples(media_path: str) -> np.ndarray:
    """Decode a media file's audio to a 1-D float32 array of 16 kHz mono samples."""
    if not os.path.isfile(media_path):
        raise FileNotFoundError(f"Media file not found: {media_path}")

    try:
        raw, _ = (
            ffmpeg.input(media_path)
            .output(
                "pipe:",
                format=RAW_SAMPLE_FORMAT,
                acodec="pcm_f32le",
                ac=CHANNEL_COUNT,
                ar=SAMPLE_RATE_HZ,
            )
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as error:
        detail = (error.stderr or b"").decode("utf-8", "ignore")
        raise RuntimeError(f"ffmpeg failed to decode audio from: {media_path}\n{detail}") from error

    # Copied out of the read-only pipe buffer, because torch refuses to wrap a non-writable
    # array without warning about it.
    samples = np.frombuffer(raw, dtype=np.float32).copy()
    if samples.size == 0:
        raise ValueError(f"No audio samples could be decoded from: {media_path}")
    return samples


def duration_seconds(samples: np.ndarray) -> float:
    """How long a decoded sample array plays for."""
    return len(samples) / SAMPLE_RATE_HZ
