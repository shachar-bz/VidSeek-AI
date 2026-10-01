"""The timestamp citation grammar, and checking an answer's citations against what was retrieved."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TimeSpan = tuple[float, float]

# A cited second is accepted when it lands inside a retrieved span, give or take this much.
# Tool results carry float seconds while a citation is written to a whole second, so a span
# opening at 734.6 is honestly written as either 12:14 or 12:15. Without the slack, one of
# those two faithful readings would be rejected as an invention.
SLACK_SECONDS = 1.0

_TIME = r"(?:\d{1,2}:)?\d{1,2}:[0-5]\d"

# The prompt asks for an en dash between the ends of a range, but models reach for a plain
# hyphen often enough that refusing one would spend the answer's only retry on punctuation.
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


def unverified(text: str, spans: list[TimeSpan]) -> list[str]:
    """The citations in an answer that are misshapen, or name a moment no tool returned."""

    return [attempt.group() for attempt in _ATTEMPT.finditer(text) if not _holds_up(attempt.group(), spans)]


def strip_unverified(text: str, spans: list[TimeSpan]) -> str:
    """The same answer with every citation it could not stand behind removed.

    Used where re-prompting is no longer possible: the model has spent its retry, or the
    user stopped the answer mid-sentence. Deleting the citation leaves the claim uncited
    rather than propping it up with a moment that may not exist.
    """

    cleaned = _ATTEMPT.sub(
        lambda attempt: attempt.group() if _holds_up(attempt.group(), spans) else "", text
    )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return "\n".join(line.rstrip() for line in cleaned.split("\n"))


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
class AnswerDraft:
    """What one run has retrieved and written so far.

    The agent's own streamed text is not shown to the user until it has been checked, so
    when a run ends without a checked answer — the user stopped it, or the model could not
    produce citations it could support — this is the only record of what had been written,
    and the only way to hand back the part of it that is verifiable.
    """

    text: str = ""
    spans: list[TimeSpan] = field(default_factory=list)
    rejected: bool = False

    def record(self, result: object) -> None:
        self.spans.extend(spans_of(result))

    def verifiable_text(self) -> str:
        return strip_unverified(self.text, self.spans)
