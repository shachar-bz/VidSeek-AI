"""Names every transcript segment, so a model can point at one without quoting it.

The model is never asked for a timestamp or for transcript text. It is asked for the two
segment IDs a memory runs between, and those IDs are the whole of the surface it can get
wrong: an ID either names a segment in this transcript or it does not, and an invented one
is caught by lookup rather than by reading the text back and hoping it matches.

IDs are positional and one-based — the first line of the transcript is `segment_1` — so the
IDs a reader sees in the prompt are the IDs that come back, and ordering two of them is
comparing their positions in the list.
"""

from collections.abc import Sequence

from backend.services.transcripts import SECONDS_PER_HOUR, TranscriptSegment, format_timecode

SEGMENT_ID_PREFIX = "segment_"

SEGMENT_LINE = "{segment_id} [{start}-{end}] {text}"


def format_segment_id(position: int) -> str:
    """The ID of the segment at `position`, counting the first segment as `segment_1`."""
    return f"{SEGMENT_ID_PREFIX}{position + 1}"


class UnknownSegmentIdError(KeyError):
    """The model returned a segment ID that is not in the transcript it was given."""


class SegmentIndex:
    """A transcript's segments, addressable by the IDs the model is shown.

    Built once per segmentation and used for both directions: rendering the transcript
    with its IDs attached, and resolving an ID the model returned back to the segment it
    names. Both directions read the same list, so there is no way for the IDs in the
    prompt and the IDs accepted in the response to drift apart.
    """

    def __init__(self, segments: Sequence[TranscriptSegment]):
        self.segments = list(segments)
        self._positions = {
            format_segment_id(position): position for position in range(len(self.segments))
        }

    @property
    def first_id(self) -> str:
        return format_segment_id(0)

    @property
    def last_id(self) -> str:
        return format_segment_id(len(self.segments) - 1)

    def __contains__(self, segment_id: str) -> bool:
        return segment_id in self._positions

    def __len__(self) -> int:
        return len(self.segments)

    def position(self, segment_id: str) -> int:
        """Where `segment_id` sits in the transcript, or raise if it names nothing."""
        try:
            return self._positions[segment_id]
        except KeyError:
            raise UnknownSegmentIdError(
                f"{segment_id!r} is not a segment of this transcript, which runs "
                f"{self.first_id} to {self.last_id}"
            ) from None

    def between(self, start_segment_id: str, end_segment_id: str) -> list[TranscriptSegment]:
        """The original segments from `start_segment_id` to `end_segment_id`, inclusive."""
        start = self.position(start_segment_id)
        end = self.position(end_segment_id)
        return self.segments[start : end + 1]

    def render(self) -> str:
        """The transcript as `segment_1 [MM:SS-MM:SS] text` lines, one segment each.

        The same `[MM:SS-MM:SS]` stamp the rest of the project renders, with the ID in
        front of it. The hour field is decided once for the whole transcript, as it is
        everywhere else, so every line is stamped the same width.
        """
        if not self.segments:
            return ""
        with_hours = self.segments[-1].end_seconds >= SECONDS_PER_HOUR
        return "\n".join(
            SEGMENT_LINE.format(
                segment_id=format_segment_id(position),
                start=format_timecode(segment.start_seconds, with_hours=with_hours),
                end=format_timecode(segment.end_seconds, with_hours=with_hours),
                text=segment.text,
            )
            for position, segment in enumerate(self.segments)
        )
