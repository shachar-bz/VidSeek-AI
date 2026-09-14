"""ASGI entry point for the VidSeek local companion service."""

from backend.services.video_download.web import create_app

app = create_app()

