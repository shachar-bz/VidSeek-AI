"""Renders timed segments as the text form every stage after transcription reads.

The format is fixed and deliberately dull:

    [00:00-00:08] Today I want to explain why most startups fail.
    [00:08-00:17] The first reason is that founders build something nobody wants.

One line per segment, in time order, with the range a reader can type straight into a
player. Whether the timing behind it was measured per word or per caption cue makes no
difference to what comes out, which is the point: nothing downstream has to know which
service produced the transcript.

Whole seconds are enough here. Sub-second precision is preserved on the segments
themselves, so anything that needs to seek accurately reads those instead of parsing
this back out.
"""

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600

SEGMENT_LINE = "[{start}-{end}] {text}"


def format_timecode(seconds: float, *, with_hours: bool = False) -> str:
    """`MM:SS`, or `HH:MM:SS` when `with_hours` is asked for.

    The hours field is all-or-nothing across a transcript rather than per line: a video
    that crosses the hour would otherwise switch format halfway down the file, and a
    reader splitting on `:` would get a different number of fields depending on how far
    into the video it had read.
    """
    whole = max(int(round(seconds)), 0)
    minutes, remainder = divmod(whole, SECONDS_PER_MINUTE)
    if not with_hours:
        return f"{minutes:02d}:{remainder:02d}"
    hours, minutes = divmod(minutes, SECONDS_PER_MINUTE)
    return f"{hours:02d}:{minutes:02d}:{remainder:02d}"


def render_segments(segments) -> str:
    """Lay the segments out as the transcript text, one line each, in time order.

    The hour field is decided once, from the last segment's end, so every line of one
    transcript is stamped the same width.
    """
    if not segments:
        return ""
    with_hours = segments[-1].end_seconds >= SECONDS_PER_HOUR
    return "\n".join(
        SEGMENT_LINE.format(
            start=format_timecode(segment.start_seconds, with_hours=with_hours),
            end=format_timecode(segment.end_seconds, with_hours=with_hours),
            text=segment.text,
        )
        for segment in segments
    )
