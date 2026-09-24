"""Defaults applied to every backend test.

Both fixtures here keep the suite off the developer's own machine. One points the
download root at a throwaway directory, because anything the backend persists outside a
job — the transcript store, most of all — resolves its location through
`config.download_root()`, which defaults to `~/Downloads/VidSeek`; without it a test run
would write transcripts into the same folder as real downloads and could overwrite one.
The other hides `backend/.env`, so that a test cannot reach a real ElevenLabs key or
upload to a real storage container on a machine that happens to have credentials.

Between them, a test that passes on a bare checkout passes on a configured one, which is
the property that makes the suite worth trusting.

A third turns background visual indexing off. A job run in a test would otherwise hand its
video to the job manager's visual executor, which loads SigLIP 2 and keeps the GPU -- and the
test process -- busy long after the test itself has finished. A test about visual indexing
turns it back on for itself.
"""

import os

import pytest

from backend.core import config


@pytest.fixture(autouse=True, scope="session")
def download_root_in_a_temporary_directory(tmp_path_factory):
    """Point VIDSEEK_DOWNLOAD_ROOT at a directory that is thrown away after the run.

    Set in the environment rather than by patching, because `config` reads the
    environment before it reads `.env` and every caller goes through `config`.
    """
    previous = os.environ.get("VIDSEEK_DOWNLOAD_ROOT")
    os.environ["VIDSEEK_DOWNLOAD_ROOT"] = str(tmp_path_factory.mktemp("download-root"))
    yield
    if previous is None:
        del os.environ["VIDSEEK_DOWNLOAD_ROOT"]
    else:
        os.environ["VIDSEEK_DOWNLOAD_ROOT"] = previous


@pytest.fixture(autouse=True)
def ignore_local_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read configuration from the process environment alone, never from `backend/.env`.

    The environment still wins, so a test that wants a setting sets it; what it cannot do
    is inherit one nobody asked for.
    """
    monkeypatch.setattr(config, "_env_file_values", dict)


@pytest.fixture(autouse=True)
def visual_indexing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """No job started by a test schedules a real visual index in the background."""
    monkeypatch.setenv("VIDSEEK_VISUAL_INDEXING", "false")
