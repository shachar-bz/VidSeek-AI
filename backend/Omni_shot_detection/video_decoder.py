"""Decodes a video into raw RGB frames via ffmpeg, and reads its frame rate.

OmniShotCut ships its own decoder, but it passes ffmpeg the `-vsync` flag, which
ffmpeg 9 removed. This module decodes with the modern `-fps_mode` replacement and
falls back to `-vsync` on ffmpeg builds older than 5.0, so the detector works across
both. Frames are handed to the model as a numpy array, bypassing its decoder entirely.
"""

import functools

import ffmpeg
import numpy as np

# Keeps every source frame exactly as stored: no frame is duplicated or dropped, so
# frame indices in the decoded array line up with frame numbers in the source video.
PASSTHROUGH_VALUE = "passthrough"
MODERN_PASSTHROUGH_OPTION = "fps_mode"  # ffmpeg >= 5.0
LEGACY_PASSTHROUGH_OPTION = "vsync"  # ffmpeg < 9.0, removed in 9.0

_UNSUPPORTED_OPTION_MARKERS = ("unrecognized option", "option not found")


def _is_unsupported_option_error(error: ffmpeg.Error) -> bool:
    """True when ffmpeg rejected the flag itself rather than failing on the video."""
    stderr = (error.stderr or b"").decode("utf-8", "ignore").lower()
    return any(marker in stderr for marker in _UNSUPPORTED_OPTION_MARKERS)


def _decode_with_option(video_path: str, width: int, height: int, option: str) -> bytes:
    stream, _ = (
        ffmpeg.input(video_path)
        .output("pipe:", format="rawvideo", pix_fmt="rgb24", s=f"{width}x{height}",
                **{option: PASSTHROUGH_VALUE})
        .run(capture_stdout=True, capture_stderr=True)
    )
    return stream


@functools.lru_cache(maxsize=1)
def _passthrough_option_cache() -> list:
    """Holds the passthrough flag name that this ffmpeg build accepted, once known."""
    return [MODERN_PASSTHROUGH_OPTION]


def decode_video_frames(video_path: str, width: int, height: int) -> np.ndarray:
    """Decode every frame of a video, scaled to width x height, as (T, H, W, 3) RGB uint8."""
    cache = _passthrough_option_cache()
    options = [cache[0]] + [
        option
        for option in (MODERN_PASSTHROUGH_OPTION, LEGACY_PASSTHROUGH_OPTION)
        if option != cache[0]
    ]

    for index, option in enumerate(options):
        try:
            stream = _decode_with_option(video_path, width, height, option)
        except ffmpeg.Error as error:
            is_last_attempt = index == len(options) - 1
            if is_last_attempt or not _is_unsupported_option_error(error):
                stderr = (error.stderr or b"").decode("utf-8", "ignore")
                raise RuntimeError(f"ffmpeg failed to decode {video_path}\n{stderr}") from error
            continue

        cache[0] = option
        frames = np.frombuffer(stream, np.uint8).reshape(-1, height, width, 3)
        if len(frames) == 0:
            raise ValueError(f"Decoded 0 frames from: {video_path}")
        return frames


def read_video_fps(video_path: str) -> float:
    """Read the average frame rate of a video's first video stream via ffprobe."""
    probe = ffmpeg.probe(video_path)
    video_streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
    if not video_streams:
        raise ValueError(f"No video stream found in: {video_path}")

    stream = video_streams[0]
    rate = stream.get("avg_frame_rate") or "0/0"
    if rate in ("0/0", "0"):
        rate = stream.get("r_frame_rate") or "0/1"

    numerator, _, denominator = rate.partition("/")
    denominator = float(denominator or 1)
    if denominator == 0:
        raise ValueError(f"Could not determine the frame rate of: {video_path}")
    return float(numerator) / denominator
