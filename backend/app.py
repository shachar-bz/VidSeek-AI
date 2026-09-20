"""ASGI entry point for local-companion and hosted VidSeek API deployments."""

from backend.api import create_app

app = create_app()
