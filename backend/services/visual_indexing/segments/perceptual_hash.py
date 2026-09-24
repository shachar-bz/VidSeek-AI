"""A 64-bit perceptual hash (pHash) of a frame, and the distance between two of them.

The image embedding is what notices a new scene, but it can see two slides with different text
as nearly the same picture. The perceptual hash is the check that does not: it keeps the coarse
layout of light and dark in the frame, which is exactly what a new slide or a line of new
writing on a board changes.

This is the standard DCT hash: shrink to 32x32 greyscale, take the 2-D discrete cosine
transform, keep the 8x8 lowest frequencies, and set one bit per coefficient that lies above
their median. Written out here rather than taken from a package because it is these few lines
of numpy.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

HASH_IMAGE_SIDE = 32
HASH_FREQUENCY_SIDE = 8


def _dct_matrix(size: int) -> np.ndarray:
    """The orthonormal DCT-II basis: `matrix @ signal` is the transform of a column."""
    frequencies = np.arange(size)[:, None]
    positions = np.arange(size)[None, :]
    matrix = np.cos(np.pi * (2 * positions + 1) * frequencies / (2 * size))
    matrix[0] *= 1 / np.sqrt(2)
    return matrix * np.sqrt(2 / size)


_DCT = _dct_matrix(HASH_IMAGE_SIDE)


def perceptual_hash(image: Image.Image) -> int:
    """The frame's 64-bit pHash, as an integer."""
    grey = image.convert("L").resize((HASH_IMAGE_SIDE, HASH_IMAGE_SIDE), Image.Resampling.LANCZOS)
    pixels = np.asarray(grey, dtype=np.float64)
    frequencies = (_DCT @ pixels @ _DCT.T)[:HASH_FREQUENCY_SIDE, :HASH_FREQUENCY_SIDE]
    bits = (frequencies > np.median(frequencies)).flatten()
    return int("".join("1" if bit else "0" for bit in bits), 2)


def hash_distance(first: int, second: int) -> int:
    """How many of the 64 bits differ: 0 for the same picture, around 32 for unrelated ones."""
    return (first ^ second).bit_count()
