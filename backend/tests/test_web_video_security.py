"""Tests for the local companion's session, URL, header, and path boundaries."""

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services.video_download.web.models import BrowserContext
from backend.services.video_download.web.security import (
    SessionRegistry,
    filtered_headers,
    reject_youtube,
    validate_local_media_path,
    validate_remote_url,
)


def test_session_is_bound_to_allowed_extension_origin() -> None:
    registry = SessionRegistry({"allowed"})
    token = registry.create("chrome-extension://allowed")
    assert registry.verify(token, "chrome-extension://allowed")
    assert not registry.verify(token, "chrome-extension://different")
    with pytest.raises(PermissionError):
        registry.create("https://example.com")


def test_header_filter_never_forwards_unapproved_headers() -> None:
    context = BrowserContext(
        headers={"Authorization": "secret", "Host": "forbidden", "X-Leak": "forbidden"},
        user_agent="VidSeek test",
    )
    headers = filtered_headers(context)
    assert headers == {"Authorization": "secret", "User-Agent": "VidSeek test"}


def test_raw_cookie_header_is_never_forwarded() -> None:
    context = BrowserContext(headers={"Cookie": "session=secret"})
    assert "Cookie" not in filtered_headers(context)


def test_local_media_path_must_be_inside_download_root(tmp_path: Path) -> None:
    root = tmp_path / "VidSeek"
    root.mkdir()
    media = root / "recording.mp4"
    media.write_bytes(b"video")
    with patch("backend.services.video_download.web.security.probe_media_file"):
        assert validate_local_media_path(str(media), root) == media.resolve()

    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    with patch("backend.services.video_download.web.security.probe_media_file"):
        with pytest.raises(ValueError, match="outside"):
            validate_local_media_path(str(outside), root)


@pytest.mark.parametrize(
    "url",
    ["https://youtube.com/watch?v=x", "https://www.youtube.com/embed/x", "https://youtu.be/x"],
)
def test_youtube_is_owned_by_the_other_pipeline(url: str) -> None:
    with pytest.raises(ValueError, match="YouTube"):
        reject_youtube(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9/secret.m3u8",
        "http://localhost/secret.m3u8",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/secret.m3u8",
    ],
)
def test_private_and_loopback_media_targets_are_blocked(url: str) -> None:
    with pytest.raises(ValueError, match="Private, loopback"):
        validate_remote_url(url)


@pytest.mark.parametrize(
    "url",
    ["file:///C:/Windows/win.ini", "ftp://example.com/clip.mp4", "https://user:pass@example.com/a"],
)
def test_non_web_and_credentialed_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_remote_url(url)


@pytest.mark.parametrize(
    "url",
    ["https://m.youtube.com/watch?v=x", "https://music.youtube.com/watch?v=x",
     "https://www.youtube-nocookie.com/embed/x"],
)
def test_youtube_subdomains_are_owned_by_the_other_pipeline(url: str) -> None:
    with pytest.raises(ValueError, match="YouTube"):
        reject_youtube(url)


def test_header_names_are_folded_so_only_one_user_agent_is_sent() -> None:
    """Chrome's debugger reports header names lowercased; both spellings must not survive."""
    context = BrowserContext(user_agent="popup agent")
    headers = filtered_headers(context, {"user-agent": "captured agent"})
    assert list(headers.values()) == ["captured agent"]
    assert len(headers) == 1


def test_a_path_chrome_no_longer_holds_is_a_validation_error(tmp_path: Path) -> None:
    """Must stay a ValueError, so the API answers 422 rather than 500."""
    root = tmp_path / "VidSeek"
    root.mkdir()
    with pytest.raises(ValueError, match="does not exist"):
        validate_local_media_path(str(root / "gone.mp4"), root)
