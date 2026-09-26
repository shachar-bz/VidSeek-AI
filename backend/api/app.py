"""Builds the VidSeek FastAPI app: state, middleware, error shaping, and routes."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core import config
from backend.core.auth import UserAuthRegistry
from backend.core.security import SessionRegistry
from backend.services.video_download.jobs import JobManager
from backend.storage.blob.video_storage import BlobVideoStorage
from backend.storage.postgres import (
    PostgresChapters,
    PostgresComments,
    PostgresConversations,
    PostgresLibraryViews,
    PostgresMessages,
    PostgresPinnedAnswers,
    PostgresSessions,
    PostgresTranscriptSegments,
    PostgresUsers,
    PostgresUserVideos,
    PostgresVideoJobs,
    PostgresVideoRecords,
)
from backend.video_agent import ConversationAgentRunner, PydanticConversationAgentRunner
from backend.video_agent.generation import GenerationRegistry

from .routes import account, auth, conversations, health, library, sessions, video_jobs, videos

LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "testclient"}


def create_app(
    *,
    session_registry: SessionRegistry | None = None,
    job_manager: JobManager | None = None,
    user_auth_registry: UserAuthRegistry | None = None,
    users_store: PostgresUsers | None = None,
    sessions_store: PostgresSessions | None = None,
    library_views_store: PostgresLibraryViews | None = None,
    user_videos_store: PostgresUserVideos | None = None,
    transcript_segments_store: PostgresTranscriptSegments | None = None,
    chapters_store: PostgresChapters | None = None,
    pinned_answers_store: PostgresPinnedAnswers | None = None,
    conversations_store: PostgresConversations | None = None,
    messages_store: PostgresMessages | None = None,
    video_records_store: PostgresVideoRecords | None = None,
    comments_store: PostgresComments | None = None,
    video_jobs_store: PostgresVideoJobs | None = None,
    blob_video_storage: BlobVideoStorage | None = None,
    conversation_agent_runner: ConversationAgentRunner | None = None,
    generation_registry: GenerationRegistry | None = None,
) -> FastAPI:
    """Build the local or hosted API with injectable process-owned dependencies."""
    registry = (
        session_registry if session_registry is not None else SessionRegistry.from_environment()
    )
    manager = job_manager if job_manager is not None else JobManager(config.download_root())
    # Nothing is queried yet: these Postgres stores only reach the pool when a route
    # actually calls them, so building them needs no database, the same as every other
    # Postgres store.
    store = users_store if users_store is not None else PostgresUsers()
    durable_sessions = sessions_store if sessions_store is not None else PostgresSessions()
    auth_registry = (
        user_auth_registry
        if user_auth_registry is not None
        else UserAuthRegistry(durable_sessions)
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(title="VidSeek API", version="1.0.0", lifespan=lifespan)
    app.state.session_registry = registry
    app.state.job_manager = manager
    app.state.user_auth_registry = auth_registry
    app.state.users_store = store
    app.state.sessions_store = durable_sessions
    app.state.library_views_store = (
        library_views_store if library_views_store is not None else PostgresLibraryViews()
    )
    app.state.user_videos_store = (
        user_videos_store if user_videos_store is not None else PostgresUserVideos()
    )
    app.state.transcript_segments_store = (
        transcript_segments_store
        if transcript_segments_store is not None
        else PostgresTranscriptSegments()
    )
    app.state.chapters_store = (
        chapters_store if chapters_store is not None else PostgresChapters()
    )
    app.state.pinned_answers_store = (
        pinned_answers_store
        if pinned_answers_store is not None
        else PostgresPinnedAnswers()
    )
    app.state.conversations_store = (
        conversations_store
        if conversations_store is not None
        else PostgresConversations()
    )
    app.state.messages_store = (
        messages_store if messages_store is not None else PostgresMessages()
    )
    app.state.video_records_store = (
        video_records_store if video_records_store is not None else PostgresVideoRecords()
    )
    app.state.comments_store = (
        comments_store if comments_store is not None else PostgresComments()
    )
    app.state.video_jobs_store = (
        video_jobs_store if video_jobs_store is not None else PostgresVideoJobs()
    )
    # Blob settings are required only by playback. Keeping an absent default lazy preserves
    # startup for a local companion with no storage configuration.
    app.state.blob_video_storage = blob_video_storage
    app.state.conversation_agent_runner = (
        conversation_agent_runner
        if conversation_agent_runner is not None
        else PydanticConversationAgentRunner()
    )
    app.state.generation_registry = (
        generation_registry if generation_registry is not None else GenerationRegistry()
    )

    # Starlette runs the last-registered middleware outermost, so CORS must be added
    # before the loopback gate to keep running inside it, as it did before this split.
    # Reversing the two silently changes preflight behavior for non-loopback clients.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(
            config.website_origins()
            | {f"chrome-extension://{item}" for item in config.extension_ids()}
        ),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-VidSeek-User-Token"],
    )

    if config.require_loopback():
        @app.middleware("http")
        async def require_loopback(request: Request, call_next):
            client_host = request.client.host if request.client else ""
            if client_host not in LOOPBACK_CLIENTS:
                return JSONResponse(
                    status_code=403, content={"detail": "Loopback access only"}
                )
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
    app.include_router(auth.router)
    app.include_router(video_jobs.router)
    app.include_router(account.router)
    app.include_router(library.router)
    app.include_router(videos.router)
    app.include_router(conversations.router)
    return app
