"""Liveness probe, used by the extension to find out whether the companion is running."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    # The job manager's own root, not `config.download_root()` directly: a test (or any
    # other caller of `create_app`) can inject a `JobManager` with a different root, and
    # that instance is what actually enforces the check this value exists to explain.
    download_root = request.app.state.job_manager.download_root
    return {"status": "ok", "download_root": str(download_root)}
