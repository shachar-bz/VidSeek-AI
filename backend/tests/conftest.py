"""Defaults applied to every backend test.

The suite reads configuration from the process environment alone. Without this, the same
test passes on a machine with no `backend/.env` and, on a machine that has one, quietly
reaches a real ElevenLabs key or uploads to a real R2 bucket — which is exactly the sort
of difference that makes a test suite untrustworthy.
"""

import pytest

from backend.core import config


@pytest.fixture(autouse=True)
def ignore_local_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_env_file_values", dict)
