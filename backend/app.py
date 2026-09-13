"""ASGI entry point for the VidSeek local companion service."""

from .Web_video_download import create_app

app = create_app()

