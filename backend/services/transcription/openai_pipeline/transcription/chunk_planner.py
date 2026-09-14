"""Plans where to split audio that is too long for one transcription request.

The transcription API accepts a little under an hour of audio per request and transcribes
all of it, so most videos need no splitting at all and this module returns a single span
for them. When a video does exceed the ceiling, cutting it at an arbitrary second would
land mid-word, so split points are chosen in silence instead, preferring a silence gap
that also coincides with a shot boundary.

Shot boundaries are passed in as plain (start_seconds, end_seconds) pairs, so this module
depends on neither of the shot detection modules and works fine without them.

Requires the ffmpeg binary on PATH.
"""

import ffmpeg

# How quiet, and for how long, a stretch has to be before it counts as a gap worth cutting
# in. -30 dBFS keeps room tone and background music from reading as speech, and a third of
# a second is about the shortest pause a speaker leaves between sentences.
SILENCE_THRESHOLD_DB = -30.0
MIN_SILENCE_SECONDS = 0.3

# A split is allowed to land this far from the target before a nearer silence gap stops
# being worth preferring. Wide, because a cut in silence is worth much more than a cut at
# an exact second.
SPLIT_SEARCH_WINDOW_SECONDS = 60.0

# How close a shot boundary must sit to a silence gap to count as the same moment.
SHOT_BOUNDARY_TOLERANCE_SECONDS = 0.5


def detect_silence_intervals(audio_path: str) -> list[tuple[float, float]]:
    """Find every silent stretch in an audio file, as (start_seconds, end_seconds) pairs.

    Uses ffmpeg's `silencedetect`, which reports its findings on stderr rather than as
    output, so the filter graph is rendered to null and the log is parsed.
    """
    try:
        _, stderr = (
            ffmpeg.input(audio_path)
            .filter("silencedetect", noise=f"{SILENCE_THRESHOLD_DB}dB", d=MIN_SILENCE_SECONDS)
            .output("-", format="null")
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as error:
        detail = (error.stderr or b"").decode("utf-8", "ignore")
        raise RuntimeError(f"ffmpeg failed to detect silence in: {audio_path}\n{detail}") from error

    intervals: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in stderr.decode("utf-8", "ignore").splitlines():
        if "silence_start:" in line:
            pending_start = float(line.rsplit("silence_start:", 1)[1].split()[0])
        elif "silence_end:" in line and pending_start is not None:
            end = float(line.rsplit("silence_end:", 1)[1].split()[0])
            intervals.append((pending_start, end))
            pending_start = None
    return intervals


def _silence_midpoints(intervals: list[tuple[float, float]]) -> list[float]:
    """The safest instant to cut within each silent stretch: the middle of it."""
    return [(start + end) / 2 for start, end in intervals]


def _nearest(candidates: list[float], target: float, window: float) -> float | None:
    """The candidate closest to `target`, or None if none falls within `window` of it."""
    within_window = [c for c in candidates if abs(c - target) <= window]
    return min(within_window, key=lambda c: abs(c - target)) if within_window else None


def _choose_split_point(
    target_seconds: float,
    silence_points: list[float],
    shot_boundary_seconds: list[float],
    search_window_seconds: float,
) -> tuple[float, str]:
    """Pick where to cut near `target_seconds`, and say which rule chose it.

    Dialogue routinely continues across a shot boundary, so a shot boundary alone is not a
    safe place to cut. One that falls inside a silence gap is, and it is the best of both:
    the cut is silent and it lines up with a visual change.
    """
    quiet_shot_boundaries = [
        boundary
        for boundary in shot_boundary_seconds
        if any(
            abs(boundary - point) <= SHOT_BOUNDARY_TOLERANCE_SECONDS for point in silence_points
        )
    ]

    chosen = _nearest(quiet_shot_boundaries, target_seconds, search_window_seconds)
    if chosen is not None:
        return chosen, "shot boundary in silence"

    chosen = _nearest(silence_points, target_seconds, search_window_seconds)
    if chosen is not None:
        return chosen, "silence"

    return target_seconds, "hard cut (no silence found nearby)"


def plan_chunk_spans(
    duration_seconds: float,
    target_chunk_seconds: float,
    *,
    silence_intervals: list[tuple[float, float]] | None = None,
    shot_spans: list[tuple[float, float]] | None = None,
    search_window_seconds: float = SPLIT_SEARCH_WINDOW_SECONDS,
) -> list[tuple[float, float, str]]:
    """Split [0, duration_seconds) into spans no longer than `target_chunk_seconds`.

    Returns (start_seconds, end_seconds, reason) tuples that tile the whole duration back
    to back, where `reason` records how each span's end was chosen so that a caller can log
    the cuts that had to be made in speech.
    """
    if duration_seconds <= target_chunk_seconds:
        return [(0.0, duration_seconds, "whole video")]

    silence_points = _silence_midpoints(silence_intervals or [])
    shot_boundary_seconds = [start for start, _ in (shot_spans or []) if start > 0]

    spans: list[tuple[float, float, str]] = []
    start = 0.0
    while duration_seconds - start > target_chunk_seconds:
        target = start + target_chunk_seconds
        # Never let the search pick a point that would leave an empty or over-long span.
        window = min(search_window_seconds, target_chunk_seconds / 2)
        candidates_after_start = [point for point in silence_points if point > start + window]
        split, reason = _choose_split_point(
            target, candidates_after_start, shot_boundary_seconds, window
        )
        spans.append((start, split, reason))
        start = split

    spans.append((start, duration_seconds, "end of video"))
    return spans
