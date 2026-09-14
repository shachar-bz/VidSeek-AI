"""Extracts a video's audio as a 16 kHz mono MP3, sized for the transcription API.

The transcription endpoint caps uploads at 25 MB. At 64 kbps that is about 52 minutes of
audio, which is longer than the API's own duration ceiling, so encoding this way takes
file size out of the picture entirely and leaves duration as the only limit to plan around.

Requires the ffmpeg binary on PATH.
"""

import os
import tempfile
from contextlib import contextmanager

import ffmpeg

# Speech recognition models downsample to 16 kHz mono anyway, so sending anything richer
# only costs upload time. 64 kbps is transparent for speech at this sample rate.
SAMPLE_RATE_HZ = 16000
CHANNEL_COUNT = 1
BITRATE = "64k"
AUDIO_CODEC = "libmp3lame"
AUDIO_SUFFIX = ".mp3"


def _describe_ffmpeg_failure(error: ffmpeg.Error, action: str, path: str) -> RuntimeError:
    stderr = (error.stderr or b"").decode("utf-8", "ignore")
    return RuntimeError(f"ffmpeg failed to {action}: {path}\n{stderr}")


def extract_audio(video_path: str, audio_path: str) -> str:
    """Write `video_path`'s audio track to `audio_path` as 16 kHz mono MP3, and return it."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    try:
        (
            ffmpeg.input(video_path)
            .output(
                audio_path,
                vn=None,
                acodec=AUDIO_CODEC,
                ac=CHANNEL_COUNT,
                ar=SAMPLE_RATE_HZ,
                audio_bitrate=BITRATE,
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as error:
        raise _describe_ffmpeg_failure(error, "extract audio from", video_path) from error

    if not os.path.isfile(audio_path) or os.path.getsize(audio_path) == 0:
        raise RuntimeError(f"No audio track could be extracted from: {video_path}")
    return audio_path


@contextmanager
def extracted_audio(video_path: str):
    """Extract a video's audio to a temporary file, deleting it when the block exits."""
    handle, audio_path = tempfile.mkstemp(suffix=AUDIO_SUFFIX)
    os.close(handle)
    try:
        yield extract_audio(video_path, audio_path)
    finally:
        try:
            os.remove(audio_path)
        except OSError:
            pass


def read_duration_seconds(media_path: str) -> float:
    """Read a media file's duration in seconds via ffprobe."""
    try:
        probe = ffmpeg.probe(media_path)
    except ffmpeg.Error as error:
        raise _describe_ffmpeg_failure(error, "probe", media_path) from error

    duration = probe.get("format", {}).get("duration")
    if duration is None:
        raise ValueError(f"Could not determine the duration of: {media_path}")
    return float(duration)


def cut_audio(audio_path: str, output_path: str, start_seconds: float, end_seconds: float) -> str:
    """Copy the [start_seconds, end_seconds) span of an audio file into `output_path`.

    The MP3 frames are copied rather than re-encoded, so cutting a long file into chunks
    costs no quality and takes roughly as long as writing the bytes out.
    """
    try:
        (
            ffmpeg.input(audio_path, ss=start_seconds, t=end_seconds - start_seconds)
            .output(output_path, acodec="copy")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as error:
        raise _describe_ffmpeg_failure(error, "cut", audio_path) from error
    return output_path
