"""The timestamp citation grammar, and checking each citation of a streamed answer against what was retrieved."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TimeSpan = tuple[float, float]

# A cited second is accepted when it lands inside a retrieved span, give or take this much.
# Tool results carry float seconds while a citation is written to a whole second, so a span
# opening at 734.6 is honestly written as either 12:14 or 12:15. Without the slack, one of
# those two faithful readings would be rejected as an invention.
SLACK_SECONDS = 1.0

# A well-formed citation is at most "[1:23:45 – 1:23:45]" plus a little spacing. A bracket that
# stays open past this is prose that happens to contain a "[", and holding it back any longer
# would only delay text the reader is waiting for.
MAX_CITATION_LENGTH = 40

_TIME = r"(?:\d{1,2}:)?\d{1,2}:[0-5]\d"

# The prompt asks for an en dash between the ends of a range, but models reach for a plain
# hyphen often enough that refusing one would drop a faithful citation over punctuation.
_DASH = r"[-\u2013\u2014]"

_CITATION = re.compile(
    rf"\[\s*(?P<start>{_TIME})\s*(?:{_DASH}\s*(?P<end>{_TIME})\s*)?\]"
)

# Anything bracketed that reaches for a time, so that a misshapen attempt like [12:1] is
# caught as a violation rather than quietly ignored for not being a citation. A bracket
# holding no digit:digit pair was never trying to be a timestamp and is left alone.
_ATTEMPT = re.compile(r"\[[^\[\]]*\d:\d[^\[\]]*\]")


def seconds_of(timestamp: str) -> float:
    """The second a well-formed `MM:SS` or `H:MM:SS` timestamp names."""

    parts = [int(part) for part in timestamp.split(":")]
    hours, minutes, secs = ([0] * (3 - len(parts))) + parts
    return float(hours * 3600 + minutes * 60 + secs)


def spans_of(result: object) -> list[TimeSpan]:
    """Every start/end pair anywhere inside one tool's return value.

    The walk is structural rather than typed because the five tools nest their times
    differently: a search returns its moments in a list beside a note, a chapter carries its own range plus
    one per memory it contains, and a memory context holds a target with neighbours either
    side. Reading whatever carries both fields keeps this from needing an update every time
    a result model grows a field.
    """

    found: list[TimeSpan] = []
    _collect(result, found)
    return found


def _collect(value: object, found: list[TimeSpan]) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        start, end = value.get("start_seconds"), value.get("end_seconds")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            found.append((float(start), float(end)))
        for item in value.values():
            _collect(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect(item, found)


def _holds_up(attempt: str, spans: list[TimeSpan]) -> bool:
    match = _CITATION.fullmatch(attempt)
    if match is None:
        return False
    ends = [match.group("start"), match.group("end")]
    return all(_retrieved(seconds_of(end), spans) for end in ends if end is not None)


def _retrieved(second: float, spans: list[TimeSpan]) -> bool:
    return any(
        start - SLACK_SECONDS <= second <= end + SLACK_SECONDS for start, end in spans
    )


@dataclass
class RetrievedSpans:
    """The moments the tools have returned, which are the only ones an answer may cite.

    Filled from this turn's tool results, and before the turn starts from the earlier turns of
    the conversation (see `restore`). A time that only ever appeared in chat text was never
    returned by a tool, so it is never added here.
    """

    spans: list[TimeSpan] = field(default_factory=list)

    def record(self, result: object) -> None:
        self.spans.extend(spans_of(result))

    def restore(self, earlier: list[TimeSpan]) -> None:
        self.spans.extend(earlier)


class CitationFilter:
    """Passes a streamed answer through, holding back and checking each citation as it closes.

    Both checks a citation must pass, its shape and its being inside a retrieved span, need
    only the bracket itself, so they run the moment the closing `]` arrives rather than once
    the answer is whole. The text before and after streams through untouched. A citation that
    fails is dropped together with the space before it, which leaves the claim uncited rather
    than propping it up with a moment that may not exist.
    """

    def __init__(self, spans: list[TimeSpan]):
        self._spans = spans
        self._space = ""
        self._open = ""
        self._lead = ""

    def feed(self, text: str) -> str:
        """What can be shown of the answer now, given the next piece of it."""

        shown: list[str] = []
        for character in text:
            if self._open:
                self._extend_bracket(character, shown)
            elif character == "[":
                self._open, self._lead, self._space = "[", self._space, ""
            elif character in " \t":
                shown.append(self._space)
                self._space = character
            else:
                shown.append(self._space + character)
                self._space = ""
        return "".join(shown)

    def finish(self) -> str:
        """The held-back tail once the answer has ended: a bracket that never closed is just prose."""

        tail = self._space + self._lead + self._open
        self._space = self._lead = self._open = ""
        return tail

    def _extend_bracket(self, character: str, shown: list[str]) -> None:
        if character == "[":
            # The earlier "[" never closed, so it was not a citation; this one may be.
            shown.append(self._lead + self._open)
            self._open, self._lead = "[", ""
            return
        self._open += character
        if character == "]":
            bracket, lead = self._open, self._lead
            self._open = self._lead = ""
            if _ATTEMPT.fullmatch(bracket) is None or _holds_up(bracket, self._spans):
                shown.append(lead + bracket)
            return
        if len(self._open) > MAX_CITATION_LENGTH:
            shown.append(self._lead + self._open)
            self._open = self._lead = ""
