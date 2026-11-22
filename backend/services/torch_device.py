"""Picks the device the in-process torch models run on: an NVIDIA GPU, an Apple GPU, or the CPU.

CUDA comes first, then MPS (the GPU of an Apple Silicon Mac), then the CPU. Every model this
process loads itself goes through here, so one machine runs them all on the same device.
"""

from __future__ import annotations

import torch

CUDA = "cuda"
MPS = "mps"
CPU = "cpu"


def preferred_torch_device() -> str:
    """The fastest device this machine offers torch: `cuda`, else `mps`, else `cpu`."""
    if torch.cuda.is_available():
        return CUDA
    if torch.backends.mps.is_available():
        return MPS
    return CPU
