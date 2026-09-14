"""ASGI entry point for the VidSeek local companion service."""

from backend.api import create_app

app = create_app()
