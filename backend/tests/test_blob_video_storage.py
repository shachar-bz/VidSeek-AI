"""Tests for the Azure Blob Storage settings, blob names and video upload behaviour."""

from pathlib import Path

import pytest
from azure.core.exceptions import ResourceNotFoundError

from backend.storage.blob import BlobSettings, BlobVideoStorage, build_video_key, is_blob_configured
from backend.storage.blob.settings import load_blob_settings

ACCOUNT_KEY = "a2V5LWJ5dGVz=="
CONNECTION_STRING = (
    "DefaultEndpointsProtocol=https;AccountName=vidseekstg;"
    f"AccountKey={ACCOUNT_KEY};EndpointSuffix=core.windows.net"
)

SETTINGS = BlobSettings(
    connection_string=CONNECTION_STRING,
    container="videos",
    account_name="vidseekstg",
    account_key=ACCOUNT_KEY,
)


class FakeBlob:
    """One blob, recording what the storage would have sent."""

    def __init__(self, client, name: str):
        self._client = client
        self.name = name

    @property
    def url(self) -> str:
        return f"https://vidseekstg.blob.core.windows.net/videos/{self.name}"

    def upload_blob(
        self, data, *, overwrite=None, content_settings=None, max_concurrency=None, progress_hook=None
    ):
        self._client.uploads.append(
            {
                "name": self.name,
                "overwrite": overwrite,
                "content_type": content_settings.content_type if content_settings else None,
                "bytes": data.read(),
            }
        )
        if progress_hook is not None:
            for uploaded, total in self._client.progress:
                progress_hook(uploaded, total)

    def exists(self) -> bool:
        if self._client.missing:
            return False
        return True

    def delete_blob(self) -> None:
        if self._client.missing:
            raise ResourceNotFoundError("The specified blob does not exist.")
        self._client.deleted.append(self.name)


class FakeBlobServiceClient:
    """Stands in for the storage account, and answers the way the SDK does."""

    def __init__(self, *, missing: bool = False, progress=((4, 11), (11, 11))):
        self.uploads: list[dict] = []
        self.deleted: list[str] = []
        self.missing = missing
        self.progress = progress

    def get_blob_client(self, container: str, blob: str) -> FakeBlob:
        self.container = container
        return FakeBlob(self, blob)


def _storage(client: FakeBlobServiceClient, settings: BlobSettings = SETTINGS) -> BlobVideoStorage:
    return BlobVideoStorage(client=client, settings=settings)


def _video(tmp_path: Path, name: str = "My Talk.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"video-bytes")
    return path


def test_name_puts_every_file_of_one_video_under_its_own_prefix() -> None:
    assert build_video_key("job-42", "clip.mp4") == "videos/job-42/clip.mp4"


def test_name_replaces_characters_that_would_not_survive_a_url() -> None:
    # A page title reaches the filename unedited, so spaces, slashes and non-Latin text
    # all arrive here; what matters is that the result is still one readable segment.
    assert build_video_key("job 1", "a/b הרצאה.mp4") == "videos/job-1/a-b-.mp4"


def test_name_refuses_a_segment_with_nothing_usable_left() -> None:
    with pytest.raises(ValueError):
        build_video_key("///", "clip.mp4")


def test_upload_sends_the_file_under_its_blob_name_with_a_video_content_type(
    tmp_path: Path,
) -> None:
    client = FakeBlobServiceClient()
    stored = _storage(client).upload_video(_video(tmp_path), video_id="job-42")

    assert stored.name == "videos/job-42/My-Talk.mp4"
    assert stored.container == "videos"
    assert stored.size_bytes == len(b"video-bytes")
    assert stored.content_type == "video/mp4"
    assert client.uploads[0]["content_type"] == "video/mp4"
    assert client.uploads[0]["bytes"] == b"video-bytes"


def test_upload_replaces_whatever_sits_under_the_same_name(tmp_path: Path) -> None:
    # A second run of the same job writes the same name, and the `videos` row that
    # describes it is keyed on that name; leaving the old blob would leave the row
    # describing a file nobody uploaded.
    client = FakeBlobServiceClient()
    _storage(client).upload_video(_video(tmp_path), video_id="job-42")

    assert client.uploads[0]["overwrite"] is True


def test_upload_of_a_matroska_file_is_not_left_to_the_machine_s_mime_registry(
    tmp_path: Path,
) -> None:
    client = FakeBlobServiceClient()
    stored = _storage(client).upload_video(_video(tmp_path, "clip.mkv"), video_id="job-42")

    assert stored.content_type == "video/x-matroska"


def test_upload_progress_is_reported_as_bytes_out_of_the_file_s_own_size(
    tmp_path: Path,
) -> None:
    reported: list[tuple[int, int]] = []
    _storage(FakeBlobServiceClient()).upload_video(
        _video(tmp_path),
        video_id="job-42",
        progress_callback=lambda done, total: reported.append((done, total)),
    )

    assert reported == [(4, 11), (11, 11)]


def test_upload_progress_survives_the_sdk_not_knowing_the_total_yet(tmp_path: Path) -> None:
    # An upload from a file object reports None for the total until the length is
    # determined, and a progress bar cannot divide by that. The size measured before the
    # upload started stands in.
    reported: list[tuple[int, int]] = []
    client = FakeBlobServiceClient(progress=((4, None), (11, 11)))
    _storage(client).upload_video(
        _video(tmp_path),
        video_id="job-42",
        progress_callback=lambda done, total: reported.append((done, total)),
    )

    assert reported == [(4, 11), (11, 11)]


def test_a_missing_blob_is_absence_rather_than_an_error() -> None:
    assert _storage(FakeBlobServiceClient(missing=True)).video_exists("videos/a/b") is False


def test_deleting_a_blob_that_is_not_there_is_not_an_error() -> None:
    _storage(FakeBlobServiceClient(missing=True)).delete_video("videos/a/b.mp4")


def test_a_video_is_handed_out_as_an_expiring_link() -> None:
    url = _storage(FakeBlobServiceClient()).sas_download_url("videos/a/b.mp4", 600)

    # Signed with the account key, so what comes back is a credential for one blob: the
    # bare URL plus a token the container would otherwise refuse.
    assert url.startswith("https://vidseekstg.blob.core.windows.net/videos/videos/a/b.mp4?")
    assert "sig=" in url


def _set_blob_env(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    values = {
        "AZURE_STORAGE_CONNECTION_STRING": CONNECTION_STRING,
        "AZURE_STORAGE_CONTAINER_NAME": "videos",
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_blob_env(monkeypatch)

    assert load_blob_settings() == SETTINGS


def test_the_account_key_keeps_the_base64_padding_the_connection_string_carried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An account key is base64 and routinely ends in `=`, which is also the separator
    # inside a connection string. Splitting on every one would tear the padding off and
    # every signature made with the key would be wrong.
    _set_blob_env(monkeypatch)

    assert load_blob_settings().account_key == ACCOUNT_KEY


def test_the_connection_string_is_matched_whatever_case_it_was_copied_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_blob_env(
        monkeypatch,
        AZURE_STORAGE_CONNECTION_STRING=(
            f"accountname=vidseekstg;accountkey={ACCOUNT_KEY};endpointsuffix=core.windows.net"
        ),
    )

    assert load_blob_settings().account_name == "vidseekstg"


def test_a_missing_container_names_the_variable_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_blob_env(monkeypatch, AZURE_STORAGE_CONTAINER_NAME=None)

    with pytest.raises(RuntimeError, match="AZURE_STORAGE_CONTAINER_NAME"):
        load_blob_settings()


def test_a_connection_string_missing_its_key_says_which_part_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A truncated paste is the common mistake, and "AuthenticationFailed" from the service
    # several calls later does not point back at it.
    _set_blob_env(
        monkeypatch,
        AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=vidseekstg",
    )

    with pytest.raises(RuntimeError, match="AccountKey"):
        load_blob_settings()


def test_half_a_configuration_counts_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # A checkout with a container name but no credential should report the missing half
    # by name, which `load_blob_settings` does, rather than looking configured.
    _set_blob_env(monkeypatch, AZURE_STORAGE_CONNECTION_STRING=None)

    assert is_blob_configured() is False


def test_a_configured_account_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_blob_env(monkeypatch)

    assert is_blob_configured() is True
