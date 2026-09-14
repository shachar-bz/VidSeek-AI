"""Authenticated non-YouTube VOD download through yt-dlp and FFmpeg."""

from __future__ import annotations

import os
import secrets
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadCancelled, DownloadError

from .models import BrowserContext, MediaCandidate, MediaKind
from .security import (
    MissingDependencyError,
    filtered_headers,
    probe_media_file,
    reject_youtube,
    validate_remote_url,
)

FORMAT_SELECTOR = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
MEDIA_SUFFIXES = {".3gp", ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}
SUBTITLE_SUFFIXES = {".srt", ".ttml", ".vtt"}


class UnsupportedMediaError(RuntimeError):
    """The URL points to media deliberately outside the v1 scope."""


@dataclass(frozen=True)
class DownloadedVideo:
    """A completed local video and any subtitle files yt-dlp found beside it."""

    title: str
    video_path: Path
    subtitle_paths: list[Path] = field(default_factory=list)


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


class SafeYoutubeDL(YoutubeDL):
    """Validate every URL, including redirects and child playlist requests."""

    def __init__(self, params: Any, auth_origin: tuple[str, str, int | None]):
        super().__init__(params)
        self._auth_origin = auth_origin

    def urlopen(self, req):
        validate_remote_url(req.url)
        if _origin(req.url) != self._auth_origin:
            for name in list(req.headers):
                if name.lower() == "authorization":
                    req.headers.pop(name, None)
        response = super().urlopen(req)
        validate_remote_url(response.url)
        return response


def _write_cookie_jar(context: BrowserContext, directory: Path) -> Path | None:
    if not context.cookies:
        return None
    cookie_path = directory / "browser-cookies.txt"
    lines = ["# Netscape HTTP Cookie File"]
    for cookie in context.cookies:
        values = (cookie.name, cookie.value, cookie.domain, cookie.path)
        if any(any(character in value for character in "\r\n\t") for value in values):
            continue
        domain = cookie.domain
        http_only_prefix = "#HttpOnly_" if cookie.http_only else ""
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        expires = int(cookie.expiration_date or 0)
        lines.append(
            "\t".join(
                [
                    f"{http_only_prefix}{domain}",
                    include_subdomains,
                    cookie.path,
                    "TRUE" if cookie.secure else "FALSE",
                    str(expires),
                    cookie.name,
                    cookie.value,
                ]
            )
        )
    cookie_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(cookie_path, 0o600)
    except OSError:
        pass
    return cookie_path


def _validate_info(info: Mapping[str, Any] | None) -> None:
    if not info:
        raise RuntimeError("The extractor returned no media information")
    if info.get("is_live") or info.get("live_status") in {
        "is_live",
        "is_upcoming",
        "post_live",
    }:
        raise UnsupportedMediaError("Live streams are not supported")
    formats = info.get("formats") or []
    if info.get("has_drm") or (formats and all(item.get("has_drm") for item in formats)):
        raise UnsupportedMediaError("DRM-protected media is not supported")


def _download_options(
    temp_dir: Path,
    context: BrowserContext,
    preferred_language: str | None,
    cookie_path: Path | None,
    progress_callback,
    cancel_event: threading.Event,
    candidate_headers: dict[str, str] | None,
) -> Any:
    languages = []
    if preferred_language:
        languages.extend([preferred_language, preferred_language.split("-")[0]])
    languages.extend(["en", "he"])
    languages = list(dict.fromkeys(languages))

    def progress_hook(update: dict) -> None:
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        total = update.get("total_bytes") or update.get("total_bytes_estimate") or 0
        downloaded = update.get("downloaded_bytes") or 0
        if total and progress_callback:
            progress_callback(min(downloaded / total, 0.99))

    options = {
        "format": FORMAT_SELECTOR,
        "merge_output_format": "mp4/mkv",
        "outtmpl": str(temp_dir / "%(title).120B-%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "continuedl": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": languages,
        "subtitlesformat": "vtt/srt/ttml/best",
        "http_headers": filtered_headers(context, candidate_headers),
        "progress_hooks": [progress_hook],
    }
    if cookie_path:
        options["cookiefile"] = str(cookie_path)
    return options


def _download_one(
    url: str,
    temp_dir: Path,
    context: BrowserContext,
    preferred_language: str | None,
    progress_callback,
    cancel_event: threading.Event,
    candidate_headers: dict[str, str] | None = None,
) -> tuple[Any, list[Path]]:
    validate_remote_url(url)
    reject_youtube(url)
    cookie_path = _write_cookie_jar(context, temp_dir)
    options: Any = _download_options(
        temp_dir,
        context,
        preferred_language,
        cookie_path,
        progress_callback,
        cancel_event,
        candidate_headers,
    )
    try:
        with SafeYoutubeDL(options, _origin(url)) as downloader:
            info = downloader.extract_info(url, download=False)
            _validate_info(info)
            info = downloader.process_ie_result(info, download=True)
    finally:
        if cookie_path:
            cookie_path.unlink(missing_ok=True)
    return info, [path for path in temp_dir.iterdir() if path.suffix.lower() in SUBTITLE_SUFFIXES]


def _find_downloaded_media(temp_dir: Path) -> Path:
    files = [
        path
        for path in temp_dir.iterdir()
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES and not path.name.endswith(".part")
    ]
    if not files:
        raise RuntimeError("Downloader completed without producing a playable media file")
    return max(files, key=lambda item: item.stat().st_size)


def download_video(
    *,
    page_url: str,
    page_title: str,
    candidates: list[MediaCandidate],
    context: BrowserContext,
    preferred_language: str | None,
    download_root: Path,
    cancel_event: threading.Event,
    progress_callback=None,
) -> DownloadedVideo:
    """Try the page extractor, then discovered HLS/DASH/direct candidates."""
    reject_youtube(page_url)
    download_root.mkdir(parents=True, exist_ok=True)
    attempts: list[tuple[str, dict[str, str] | None]] = [(page_url, None)]
    ordered = sorted(
        candidates,
        key=lambda candidate: {
            MediaKind.HLS: 0,
            MediaKind.DASH: 1,
            MediaKind.DIRECT: 2,
        }[candidate.kind],
    )
    attempts.extend((candidate.url, candidate.headers) for candidate in ordered)

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vidseek-download-") as temp_name:
        temp_dir = Path(temp_name)
        for attempt_url, headers in attempts:
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled")
            try:
                info, subtitles = _download_one(
                    attempt_url,
                    temp_dir,
                    context,
                    preferred_language,
                    progress_callback,
                    cancel_event,
                    headers,
                )
                downloaded_path = _find_downloaded_media(temp_dir)
                probe_media_file(downloaded_path)
                destination = download_root / downloaded_path.name
                if destination.exists():
                    destination = download_root / (
                        f"{destination.stem}-{secrets.token_hex(4)}{destination.suffix}"
                    )
                shutil.move(str(downloaded_path), destination)
                moved_subtitles = []
                for subtitle in subtitles:
                    subtitle_destination = destination.with_suffix(subtitle.suffix)
                    if subtitle_destination.exists():
                        subtitle_destination = download_root / (
                            f"{destination.stem}-{subtitle.stem[-12:]}{subtitle.suffix}"
                        )
                    shutil.move(str(subtitle), subtitle_destination)
                    moved_subtitles.append(subtitle_destination)
                return DownloadedVideo(
                    title=info.get("title") or page_title,
                    video_path=destination,
                    subtitle_paths=moved_subtitles,
                )
            except (UnsupportedMediaError, MissingDependencyError):
                raise
            except (DownloadError, OSError, RuntimeError, ValueError) as error:
                errors.append(type(error).__name__)
                for child in temp_dir.iterdir():
                    if child.is_file():
                        child.unlink(missing_ok=True)
        raise RuntimeError(
            "Unable to download the authenticated media after trying the page and "
            f"{len(candidates)} discovered candidate(s) ({', '.join(errors)})"
        )
