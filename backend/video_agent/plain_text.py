"""Removing markdown bold markers from a streamed answer, however the stream splits them."""

from __future__ import annotations

BOLD_MARKER = "**"


class BoldMarkerFilter:
    """Passes a streamed answer through with every `**` removed, leaving the bolded words.

    The prompt asks for plain text, but a model still reaches for bold now and then, and the
    reader should not see the asterisks when it does. A `**` can arrive split across two
    pieces of the stream, so a single `*` is held back until the next character shows whether
    it starts a marker. A lone `*`, such as a bullet or a footnote, is passed through as written.
    """

    def __init__(self) -> None:
        self._held_star = False

    def feed(self, text: str) -> str:
        """What can be shown of the answer now, given the next piece of it."""

        shown: list[str] = []
        for character in text:
            if self._held_star:
                self._held_star = False
                if character == "*":
                    continue
                shown.append("*")
            if character == "*":
                self._held_star = True
            else:
                shown.append(character)
        return "".join(shown)

    def finish(self) -> str:
        """The held-back tail once the answer has ended."""

        tail = "*" if self._held_star else ""
        self._held_star = False
        return tail
