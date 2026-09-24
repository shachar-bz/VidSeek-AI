"""Lays several frames out as one labelled grid image, and spaces frames across a window.

One frame cannot show an action -- "picks up the cup" is a change between frames -- so the
visual sub-agent looks at a sequence instead. Sent as one grid, a sequence costs one image
rather than one per frame. Every cell is stamped with its time, so the model can say *when* in
the window something happened, not only that it did.

The layout is a starting point. DeepSeek's vision model caps an image at 384 tokens, which can
make a large grid unreadable; the eval (VISUAL_UNDERSTANDING_PLAN.md §8) is what settles the
cell size and the number of columns.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from .extraction import ExtractedFrame

# The long side of one cell; a 3x3 grid of these is under 1,000 px wide.
CELL_LONG_SIDE = 320

# Space between cells, and the colour behind them.
CELL_GAP = 4
BACKGROUND = (16, 16, 16)

# The timestamp label in each cell's top-left corner.
LABEL_PADDING = 3
LABEL_BACKGROUND = (0, 0, 0)
LABEL_TEXT = (255, 255, 255)
LABEL_FONT_SIZE = 16

GRID_JPEG_QUALITY = 85


def evenly_spaced_times(start_seconds: float, end_seconds: float, count: int) -> list[float]:
    """`count` times spread across the window, both ends included when there is room for them."""
    if count <= 0:
        return []
    if count == 1 or end_seconds <= start_seconds:
        return [start_seconds]
    step = (end_seconds - start_seconds) / (count - 1)
    return [start_seconds + step * position for position in range(count)]


def build_frame_grid(
    frames: Sequence[ExtractedFrame],
    *,
    columns: int | None = None,
    cell_long_side: int = CELL_LONG_SIDE,
) -> bytes:
    """One JPEG holding every frame in order, left to right and top to bottom, each timestamped.

    `columns` defaults to the smallest square layout that fits them all.
    """
    if not frames:
        raise ValueError("A grid needs at least one frame")
    images = [Image.open(io.BytesIO(frame.image_bytes)).convert("RGB") for frame in frames]
    for image in images:
        image.thumbnail((cell_long_side, cell_long_side))
    cell_width = max(image.width for image in images)
    cell_height = max(image.height for image in images)
    column_count = columns or math.ceil(math.sqrt(len(images)))
    row_count = math.ceil(len(images) / column_count)

    grid = Image.new(
        "RGB",
        (
            column_count * cell_width + (column_count - 1) * CELL_GAP,
            row_count * cell_height + (row_count - 1) * CELL_GAP,
        ),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(grid)
    font = _label_font()
    for position, (frame, image) in enumerate(zip(frames, images)):
        row, column = divmod(position, column_count)
        left = column * (cell_width + CELL_GAP) + (cell_width - image.width) // 2
        top = row * (cell_height + CELL_GAP) + (cell_height - image.height) // 2
        grid.paste(image, (left, top))
        _draw_label(draw, font, format_timestamp(frame.time_seconds), left, top)

    output = io.BytesIO()
    grid.save(output, format="JPEG", quality=GRID_JPEG_QUALITY)
    return output.getvalue()


def format_timestamp(seconds: float) -> str:
    """`MM:SS`, or `H:MM:SS` from an hour in: the same spelling the agent cites times in."""
    whole = int(max(seconds, 0.0))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _draw_label(draw: ImageDraw.ImageDraw, font, text: str, left: int, top: int) -> None:
    """A white-on-black label, readable over any frame."""
    x0, y0, x1, y1 = draw.textbbox((left + LABEL_PADDING, top + LABEL_PADDING), text, font=font)
    draw.rectangle(
        (x0 - LABEL_PADDING, y0 - LABEL_PADDING, x1 + LABEL_PADDING, y1 + LABEL_PADDING),
        fill=LABEL_BACKGROUND,
    )
    draw.text((left + LABEL_PADDING, top + LABEL_PADDING), text, fill=LABEL_TEXT, font=font)


def _label_font():
    """A scalable font when Pillow can find one, and its built-in bitmap font otherwise."""
    try:
        return ImageFont.load_default(size=LABEL_FONT_SIZE)
    except TypeError:
        return ImageFont.load_default()
