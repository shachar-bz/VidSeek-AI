"""Builds the companion FastAPI app: state, middleware, error shaping, and routes."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core import config
from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager

from .routes import health, sessions, video_jobs

LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "testclient"}


def create_app(
    *,
    session_registry: SessionRegistry | None = None,
    job_manager: JobManager | None = None,
) -> FastAPI:
    """Build the companion app with injectable state for tests."""
    registry = session_registry or SessionRegistry.from_environment()
    manager = job_manager or JobManager(config.download_root())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(title="VidSeek local companion", version="1.0.0", lifespan=lifespan)
    app.state.session_registry = registry
    app.state.job_manager = manager

    # Starlette runs the last-registered middleware outermost, so CORS must be added
    # before the loopback gate to keep running inside it, as it did before this split.
    # Reversing the two silently changes preflight behavior for non-loopback clients.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"chrome-extension://{item}" for item in config.extension_ids()],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def require_loopback(request: Request, call_next):
        client_host = request.client.host if request.client else ""
        if client_host not in LOOPBACK_CLIENTS:
            return JSONResponse(status_code=403, content={"detail": "Loopback access only"})
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def redact_validation_errors(_: Request, error: RequestValidationError):
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details})

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(video_jobs.router)
    return app
