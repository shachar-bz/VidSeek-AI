"""The order the in-process torch models pick a device in: CUDA, then Apple's MPS, then the CPU."""

from unittest.mock import patch

from backend.services.torch_device import preferred_torch_device


def _machine_with(*, cuda: bool, mps: bool):
    return (
        patch("torch.cuda.is_available", return_value=cuda),
        patch("torch.backends.mps.is_available", return_value=mps),
    )


def test_an_nvidia_gpu_is_preferred_over_everything_else() -> None:
    cuda, mps = _machine_with(cuda=True, mps=True)
    with cuda, mps:
        assert preferred_torch_device() == "cuda"


def test_an_apple_gpu_is_used_when_there_is_no_nvidia_gpu() -> None:
    cuda, mps = _machine_with(cuda=False, mps=True)
    with cuda, mps:
        assert preferred_torch_device() == "mps"


def test_the_cpu_is_used_when_there_is_no_gpu() -> None:
    cuda, mps = _machine_with(cuda=False, mps=False)
    with cuda, mps:
        assert preferred_torch_device() == "cpu"
