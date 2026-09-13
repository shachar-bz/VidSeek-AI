"""FastAPI routes for the loopback Chrome-extension companion."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .downloader import UnsupportedMediaError
from .jobs import JobManager
from .models import (
    BrowserDownloadCompleteRequest,
    CaptureRetryRequest,
    CreateVideoJobRequest,
    VideoJobResponse,
)
from .security import (
    MissingDependencyError,
    SessionRegistry,
    configured_download_root,
    configured_extension_ids,
)


def create_app(
    *,
    session_registry: SessionRegistry | None = None,
    job_manager: JobManager | None = None,
) -> FastAPI:
    """Build the companion app with injectable state for tests."""
    registry = session_registry or SessionRegistry.from_environment()
    manager = job_manager or JobManager(configured_download_root())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(title="VidSeek local companion", version="1.0.0", lifespan=lifespan)
    configured_ids = configured_extension_ids()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"chrome-extension://{item}" for item in configured_ids],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def require_loopback(request: Request, call_next):
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse(status_code=403, content={"detail": "Loopback access only"})
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def redact_validation_errors(_: Request, error: RequestValidationError):
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details})

    def authorize(
        authorization: str | None = Header(default=None),
        origin: str | None = Header(default=None),
    ) -> None:
        token = authorization.removeprefix("Bearer ") if authorization else ""
        if not registry.verify(token, origin):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/session")
    def create_session(origin: str | None = Header(default=None)) -> dict[str, object]:
        try:
            token = registry.create(origin)
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        return {"token": token, "expires_in_seconds": 1800}

    @app.post(
        "/v1/video-jobs",
        response_model=VideoJobResponse,
        dependencies=[Depends(authorize)],
    )
    def create_job(payload: CreateVideoJobRequest) -> VideoJobResponse:
        try:
            return manager.create(payload)
        except (ValueError, UnsupportedMediaError) as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.get(
        "/v1/video-jobs/{job_id}",
        response_model=VideoJobResponse,
        dependencies=[Depends(authorize)],
    )
    def get_job(job_id: str) -> VideoJobResponse:
        try:
            return manager.get(job_id)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Video job was not found"
            ) from error

    @app.post(
        "/v1/video-jobs/{job_id}/download-complete",
        response_model=VideoJobResponse,
        dependencies=[Depends(authorize)],
    )
    def complete_download(
        job_id: str, payload: BrowserDownloadCompleteRequest
    ) -> VideoJobResponse:
        try:
            return manager.complete_browser_download(job_id, payload)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Video job was not found"
            ) from error
        except MissingDependencyError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post(
        "/v1/video-jobs/{job_id}/capture",
        response_model=VideoJobResponse,
        dependencies=[Depends(authorize)],
    )
    def retry_capture(job_id: str, payload: CaptureRetryRequest) -> VideoJobResponse:
        try:
            return manager.retry_with_capture(job_id, payload)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Video job was not found"
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.post(
        "/v1/video-jobs/{job_id}/cancel",
        response_model=VideoJobResponse,
        dependencies=[Depends(authorize)],
    )
    def cancel_job(job_id: str) -> VideoJobResponse:
        try:
            return manager.cancel(job_id)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Video job was not found"
            ) from error

    return app
