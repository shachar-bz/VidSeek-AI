"""Tests for extracting the exact middle frame used by library thumbnails."""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from backend.services.video_download.thumbnail import (
    ThumbnailGenerationError,
    generate_middle_frame,
)


def test_middle_frame_uses_half_the_measured_duration(tmp_path: Path) -> None:
    source = tmp_path / "video.mp4"
    output = tmp_path / "thumbnail.jpg"
    source.write_bytes(b"video")

    def fake_run(command, **kwargs):
        output.write_bytes(b"jpeg")
        return CompletedProcess(command, 0)

    with patch("backend.services.video_download.thumbnail.subprocess.run", side_effect=fake_run) as run:
        assert generate_middle_frame(source, output, duration_seconds=90) == output

    command = run.call_args.args[0]
    assert command[command.index("-ss") + 1] == "45.000000"


def test_unknown_duration_is_reported_instead_of_guessing_a_frame(tmp_path: Path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    with (
        patch(
            "backend.services.video_download.thumbnail.probe_media_duration_seconds",
            return_value=None,
        ),
        pytest.raises(ThumbnailGenerationError, match="duration"),
    ):
        generate_middle_frame(source, tmp_path / "thumbnail.jpg")
