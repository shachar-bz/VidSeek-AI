"""Test-wide fixtures for the backend suite.

The one thing here keeps the tests out of the developer's own download root. Anything the
backend persists outside a job — the transcript store, most of all — resolves its location
through `config.download_root()`, which defaults to `~/Downloads/VidSeek`. Without this a
test run would leave transcripts in the same folder as real downloads and could overwrite
one, which is a surprising thing for a test suite to do to somebody's disk.
"""

import os

import pytest


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
