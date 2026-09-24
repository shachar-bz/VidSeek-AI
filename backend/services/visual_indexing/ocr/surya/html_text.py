"""Turns the HTML Surya writes for each block it read into plain text.

Surya 2 returns every block as a fragment of HTML: `<p>` for a paragraph, `<h1>` for a
heading, `<table>` for a table, `<math>` around LaTeX. What a keyframe stores is searched by
trigram and by e5 meaning, and markup would only add noise to both, so the tags go and what
they mean for layout stays: a block-level tag or a `<br>` ends a line, a table cell is set
apart by a space. Entities are decoded; the LaTeX inside `<math>` is kept as written.
"""

from __future__ import annotations

from html.parser import HTMLParser

# Tags whose start or end is a line break in the text.
LINE_TAGS = frozenset(
    {
        "blockquote", "br", "caption", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "hr", "li", "ol", "p", "pre", "table", "tr", "ul",
    }
)

# Tags whose content is set apart from its neighbours by a space.
CELL_TAGS = frozenset({"td", "th"})


def html_to_text(html: str) -> str:
    """The text of one block, line breaks where the layout had them and no empty lines."""
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    lines = "".join(collector.parts).splitlines()
    return "\n".join(line.strip() for line in lines if line.strip())


class _TextCollector(HTMLParser):
    """Collects character data and turns layout tags into whitespace."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        self._layout(tag)

    def handle_endtag(self, tag) -> None:
        self._layout(tag)

    def handle_startendtag(self, tag, attrs) -> None:
        self._layout(tag)

    def handle_data(self, data) -> None:
        self.parts.append(data)

    def _layout(self, tag: str) -> None:
        if tag in LINE_TAGS:
            self.parts.append("\n")
        elif tag in CELL_TAGS:
            self.parts.append(" ")
