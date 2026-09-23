"""Tests that run real ffmpeg on a tiny generated clip: sampling, indexing, frame extraction, grids.

The clip is made by ffmpeg itself -- ten seconds of solid red, then ten of solid blue -- so it
carries one cut at a known time and nothing needs to ship in the repository. SigLIP is stood
in for by an encoder that reads the frame's average colour, which is enough to put the cut
where the colours change. Skipped on a machine without ffmpeg, which the rest of the suite
does not need.
"""

import io
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.services.video_frames import (
    FrameExtractionError,
    build_frame_grid,
    evenly_spaced_times,
    extract_frame,
    extract_frames,
    format_timestamp,
)
from backend.services.video_frames.extraction import scrub
from backend.services.visual_indexing import (
    FrameSamplingError,
    NoFramesToIndex,
    SamplingStopped,
    build_visual_index,
)
from backend.services.visual_indexing.sampling import sample_frames
from backend.services.visual_indexing.segments import SCENE_CHANGE, VIDEO_START

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")


@pytest.fixture(scope="module")
def red_then_blue(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("clip") / "red_then_blue.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=320x180:d=10:r=10",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=10:r=10",
            "-filter_complex", "[0][1]concat=n=2:v=1:a=0,format=yuv420p",
            "-c:v", "libx264", str(path),
        ],
        check=True,
    )
    return path


def colour_encoder(images):
    """Stands in for SigLIP: a frame's vector is its normalized average colour."""
    vectors = np.array([np.asarray(image, dtype=np.float64).mean(axis=(0, 1)) + 1.0 for image in images])
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


@needs_ffmpeg
def test_sampling_takes_one_shrunken_frame_every_two_seconds(red_then_blue: Path) -> None:
    frames = list(sample_frames(red_then_blue))

    assert [frame.time_seconds for frame in frames] == [float(t) for t in range(0, 20, 2)]
    assert max(frames[0].image.size) == 384
    assert frames[0].image.getpixel((10, 10))[0] > 200  # red
    assert frames[-1].image.getpixel((10, 10))[2] > 200  # blue


@needs_ffmpeg
def test_sampling_stops_when_asked(red_then_blue: Path) -> None:
    stop = threading.Event()
    stop.set()

    with pytest.raises(SamplingStopped):
        list(sample_frames(red_then_blue, stop_event=stop))


@needs_ffmpeg
def test_a_file_ffmpeg_cannot_read_fails_without_loading_a_model(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")

    # No encoder is passed, so reaching one would load SigLIP; the failure must come first.
    with pytest.raises(FrameSamplingError):
        build_visual_index(broken)


@needs_ffmpeg
def test_indexing_finds_the_cut_and_keeps_every_frame_vector(red_then_blue: Path) -> None:
    built = build_visual_index(red_then_blue, duration_seconds=20.0, embed_images=colour_encoder)

    assert len(built.frames) == 10
    assert [(s.start_seconds, s.end_seconds, s.boundary_kind) for s in built.segments] == [
        (0.0, 10.0, VIDEO_START),
        (10.0, 20.0, SCENE_CHANGE),
    ]


def test_an_empty_decode_is_nothing_to_index(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.services.visual_indexing.indexer.sample_frames", lambda *_, **__: iter(())
    )

    with pytest.raises(NoFramesToIndex):
        build_visual_index(tmp_path / "video.mp4", embed_images=colour_encoder)


@needs_ffmpeg
def test_a_frame_is_extracted_at_the_time_asked_for_as_a_small_jpeg(red_then_blue: Path) -> None:
    red = extract_frame(str(red_then_blue), 3.0)
    blue = extract_frame(str(red_then_blue), 15.0, long_side=128)

    red_image = Image.open(io.BytesIO(red.jpeg))
    blue_image = Image.open(io.BytesIO(blue.jpeg))
    assert red_image.format == "JPEG" and max(red_image.size) <= 512
    assert max(blue_image.size) == 128
    assert red_image.convert("RGB").getpixel((5, 5))[0] > 200
    assert blue_image.convert("RGB").getpixel((5, 5))[2] > 200


@needs_ffmpeg
def test_a_batch_comes_back_in_the_order_it_was_asked_for(red_then_blue: Path) -> None:
    frames = extract_frames(str(red_then_blue), [15.0, 3.0, 12.0])

    assert [frame.time_seconds for frame in frames] == [15.0, 3.0, 12.0]


@needs_ffmpeg
def test_a_time_past_the_end_is_an_error_not_an_empty_image(red_then_blue: Path) -> None:
    with pytest.raises(FrameExtractionError, match="no frame"):
        extract_frame(str(red_then_blue), 500.0)


@needs_ffmpeg
def test_an_unreadable_source_never_repeats_its_link_in_the_error() -> None:
    # `.invalid` never resolves (RFC 2606), so this fails fast without reaching anything.
    link = "https://storage-account.invalid/videos/v.mp4?sig=SECRET&se=2026"

    with pytest.raises(FrameExtractionError) as raised:
        extract_frame(link, 1.0, timeout_seconds=20)

    assert "SECRET" not in str(raised.value)
    assert "storage-account" not in str(raised.value)


def test_scrubbing_removes_the_source_its_host_and_anything_else_url_shaped() -> None:
    message = (
        "Failed to resolve a.example; error opening https://a.example/v?sig=x "
        "after redirect to https://b.example/w?sig=y"
    )

    assert scrub(message, "https://a.example/v?sig=x") == (
        "Failed to resolve <video>; error opening <video> after redirect to <video>"
    )


@needs_ffmpeg
def test_a_grid_holds_every_frame_in_order_and_is_one_jpeg(red_then_blue: Path) -> None:
    frames = extract_frames(str(red_then_blue), [1.0, 5.0, 11.0, 15.0])

    grid = Image.open(io.BytesIO(build_frame_grid(frames, cell_long_side=160)))

    assert grid.format == "JPEG"
    width, height = grid.size
    assert width < 2 * 160 + 10 and height < 2 * 90 + 10
    # Two columns: red on the top row, blue on the bottom.
    assert grid.convert("RGB").getpixel((width // 4, height // 4 + 20))[0] > 150
    assert grid.convert("RGB").getpixel((width // 4, 3 * height // 4))[2] > 150


def test_a_grid_needs_a_frame() -> None:
    with pytest.raises(ValueError):
        build_frame_grid([])


def test_times_are_spread_across_a_window_both_ends_included() -> None:
    assert evenly_spaced_times(10.0, 20.0, 3) == [10.0, 15.0, 20.0]
    assert evenly_spaced_times(10.0, 20.0, 1) == [10.0]
    assert evenly_spaced_times(10.0, 10.0, 4) == [10.0]
    assert evenly_spaced_times(10.0, 20.0, 0) == []


def test_grid_labels_use_the_same_spelling_as_citations() -> None:
    assert format_timestamp(75.9) == "01:15"
    assert format_timestamp(3725.0) == "1:02:05"
