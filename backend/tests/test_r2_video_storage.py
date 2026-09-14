"""Tests for the Cloudflare R2 settings, object keys and video upload behaviour."""

from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from backend.storage.r2 import R2Settings, R2VideoStorage, build_video_key
from backend.storage.r2.settings import load_r2_settings

SETTINGS = R2Settings(
    access_key_id="key-id",
    secret_access_key="secret",
    endpoint_url="https://account.r2.cloudflarestorage.com",
    bucket="vidseek-videos",
)


class FakeR2Client:
    """Records what the storage would have sent, and answers like R2 does."""

    def __init__(self, head_error: ClientError | None = None):
        self.uploads: list[dict] = []
        self.deleted: list[str] = []
        self.head_error = head_error

    def upload_file(self, filename, bucket, key, ExtraArgs=None, Config=None, Callback=None):
        self.uploads.append(
            {"filename": filename, "bucket": bucket, "key": key, "extra_args": ExtraArgs}
        )
        if Callback is not None:
            for chunk in (4, 3):
                Callback(chunk)

    def head_object(self, Bucket, Key):
        if self.head_error is not None:
            raise self.head_error
        return {"ContentLength": 7}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://signed/{Params['Key']}?op={operation}&expires={ExpiresIn}"


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "HeadObject")


def _storage(client: FakeR2Client, settings: R2Settings = SETTINGS) -> R2VideoStorage:
    return R2VideoStorage(client=client, settings=settings)


def _video(tmp_path: Path, name: str = "My Talk.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"video-bytes")
    return path


def test_key_puts_every_file_of_one_video_under_its_own_prefix() -> None:
    assert build_video_key("job-42", "clip.mp4") == "videos/job-42/clip.mp4"


def test_key_replaces_characters_that_would_not_survive_a_url() -> None:
    # A page title reaches the filename unedited, so spaces, slashes and non-Latin text
    # all arrive here; what matters is that the result is still one readable segment.
    assert build_video_key("job 1", "a/b הרצאה.mp4") == "videos/job-1/a-b-.mp4"


def test_key_refuses_a_segment_with_nothing_usable_left() -> None:
    with pytest.raises(ValueError):
        build_video_key("///", "clip.mp4")


def test_upload_sends_the_file_under_its_video_key_with_a_video_content_type(
    tmp_path: Path,
) -> None:
    client = FakeR2Client()
    stored = _storage(client).upload_video(_video(tmp_path), video_id="job-42")

    assert stored.key == "videos/job-42/My-Talk.mp4"
    assert stored.bucket == "vidseek-videos"
    assert stored.size_bytes == len(b"video-bytes")
    assert stored.content_type == "video/mp4"
    assert client.uploads[0]["extra_args"] == {"ContentType": "video/mp4"}


def test_upload_of_a_matroska_file_is_not_left_to_the_machine_s_mime_registry(
    tmp_path: Path,
) -> None:
    client = FakeR2Client()
    stored = _storage(client).upload_video(_video(tmp_path, "clip.mkv"), video_id="job-42")

    assert stored.content_type == "video/x-matroska"


def test_upload_progress_accumulates_the_chunks_boto3_reports_one_by_one(
    tmp_path: Path,
) -> None:
    reported: list[tuple[int, int]] = []
    _storage(FakeR2Client()).upload_video(
        _video(tmp_path),
        video_id="job-42",
        progress_callback=lambda done, total: reported.append((done, total)),
    )

    # boto3 reports each part's size as it lands; a progress bar needs the running total.
    assert reported == [(4, 11), (7, 11)]


def test_a_missing_object_is_absence_rather_than_an_error() -> None:
    assert _storage(FakeR2Client(head_error=_client_error("404"))).video_exists("videos/a/b") is False


def test_a_rejected_object_lookup_is_raised_rather_than_read_as_absence() -> None:
    # A bad token answers 403. Reporting that as "the video is not there" would send a
    # job off to download and upload it all over again, and it would fail the same way.
    with pytest.raises(ClientError):
        _storage(FakeR2Client(head_error=_client_error("403"))).video_exists("videos/a/b")


def test_a_video_is_handed_out_as_an_expiring_link() -> None:
    storage = _storage(FakeR2Client())

    assert "expires=3600" in storage.presigned_download_url("videos/a/b.mp4")


def _set_r2_env(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    values = {
        "R2_ACCESS_KEY_ID": "key-id",
        "R2_ACCESS_KEY": "secret",
        "R2_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
        "R2_BUCKET_NAME": "vidseek-videos",
        "R2_SECRET_ACCESS_KEY": None,
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_r2_env(monkeypatch)

    assert load_r2_settings() == SETTINGS


def test_the_secret_may_also_arrive_under_its_conventional_aws_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_r2_env(monkeypatch, R2_ACCESS_KEY=None, R2_SECRET_ACCESS_KEY="secret")

    assert load_r2_settings().secret_access_key == "secret"


def test_a_missing_bucket_names_the_variable_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_r2_env(monkeypatch, R2_BUCKET_NAME=None)

    with pytest.raises(RuntimeError, match="R2_BUCKET_NAME"):
        load_r2_settings()


def test_a_missing_secret_names_both_variables_it_would_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_r2_env(monkeypatch, R2_ACCESS_KEY=None)

    with pytest.raises(RuntimeError, match="R2_ACCESS_KEY.*R2_SECRET_ACCESS_KEY"):
        load_r2_settings()


def test_an_endpoint_with_the_bucket_appended_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # boto3 appends the bucket itself, so this would silently address
    # <bucket>/<bucket>/<key> and read as a missing object on every call.
    _set_r2_env(
        monkeypatch,
        R2_ENDPOINT_URL="https://account.r2.cloudflarestorage.com/vidseek-videos",
    )

    with pytest.raises(RuntimeError, match="without the bucket"):
        load_r2_settings()


def test_a_trailing_slash_on_the_endpoint_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_r2_env(monkeypatch, R2_ENDPOINT_URL="https://account.r2.cloudflarestorage.com/")

    assert load_r2_settings().endpoint_url == "https://account.r2.cloudflarestorage.com"
