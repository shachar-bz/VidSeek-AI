"""Tests for download policy and ephemeral browser cookie handling."""

import threading
from pathlib import Path

from unittest.mock import patch

import pytest

from backend.core.errors import UnsupportedMediaError
from backend.schemas.browser import BrowserContext, BrowserCookie, MediaCandidate
from backend.services.video_download.web.downloader import (
    SafeYoutubeDL,
    _download_options,
    _origin,
    _validate_info,
    _write_cookie_jar,
    download_video,
)


def test_live_and_drm_media_are_rejected() -> None:
    with pytest.raises(UnsupportedMediaError, match="Live"):
        _validate_info({"is_live": True})
    with pytest.raises(UnsupportedMediaError, match="DRM"):
        _validate_info({"has_drm": True})


def test_cookie_jar_is_netscape_format_and_keeps_http_only(tmp_path: Path) -> None:
    context = BrowserContext(
        cookies=[
            BrowserCookie(
                name="session",
                value="secret",
                domain=".example.com",
                secure=True,
                http_only=True,
            )
        ]
    )
    path = _write_cookie_jar(context, tmp_path)
    assert path is not None
    content = path.read_text(encoding="utf-8")
    assert content.startswith("# Netscape HTTP Cookie File")
    assert "#HttpOnly_.example.com" in content
    assert "\tsession\tsecret" in content


def test_normal_options_do_not_forward_raw_cookie_header(tmp_path: Path) -> None:
    options = _download_options(
        tmp_path,
        BrowserContext(headers={"Cookie": "session=secret", "Referer": "https://example.com"}),
        None,
        None,
        None,
        threading.Event(),
        None,
    )
    assert "Cookie" not in options["http_headers"]
    assert options["http_headers"]["Referer"] == "https://example.com"



def test_extractor_returning_nothing_is_reported_rather_than_crashing() -> None:
    with pytest.raises(RuntimeError, match="no media information"):
        _validate_info(None)


def test_same_origin_requests_keep_their_authorization_header() -> None:
    """`_origin` and the constructor must agree, or every request loses its token."""
    auth_origin = _origin("https://cdn.example.com/master.m3u8")
    assert auth_origin == ("https", "cdn.example.com", 443)
    assert _origin("https://cdn.example.com/segment-1.ts") == auth_origin
    assert _origin("https://other.example.com/segment-1.ts") != auth_origin


def test_download_moves_the_media_and_its_subtitles_into_the_root(tmp_path: Path) -> None:
    """Covers the whole body of `download_video`, including the move into the root."""
    root = tmp_path / "VidSeek"

    def fake_download_one(url, temp_dir, *args, **kwargs):
        (temp_dir / "clip.mp4").write_bytes(b"video")
        (temp_dir / "clip.en.vtt").write_text("WEBVTT", encoding="utf-8")
        return {"title": "Clip"}, [temp_dir / "clip.en.vtt"]

    with patch(
        "backend.services.video_download.web.downloader._download_one", side_effect=fake_download_one
    ), patch("backend.services.video_download.web.downloader.probe_media_file"):
        result = download_video(
            page_url="https://example.com/watch",
            page_title="Fallback title",
            candidates=[MediaCandidate(kind="hls", url="https://example.com/master.m3u8")],
            context=BrowserContext(),
            preferred_language=None,
            download_root=root,
            cancel_event=threading.Event(),
        )

    assert result.title == "Clip"
    assert result.video_path == root / "clip.mp4"
    assert result.video_path.read_bytes() == b"video"
    assert [path.name for path in result.subtitle_paths] == ["clip.en.vtt"]


def test_a_name_collision_in_the_root_does_not_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "VidSeek"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"existing")

    def fake_download_one(url, temp_dir, *args, **kwargs):
        (temp_dir / "clip.mp4").write_bytes(b"new")
        return {"title": "Clip"}, []

    with patch(
        "backend.services.video_download.web.downloader._download_one", side_effect=fake_download_one
    ), patch("backend.services.video_download.web.downloader.probe_media_file"):
        result = download_video(
            page_url="https://example.com/watch",
            page_title="Clip",
            candidates=[],
            context=BrowserContext(),
            preferred_language=None,
            download_root=root,
            cancel_event=threading.Event(),
        )

    assert result.video_path != root / "clip.mp4"
    assert (root / "clip.mp4").read_bytes() == b"existing"
    assert result.video_path.read_bytes() == b"new"
