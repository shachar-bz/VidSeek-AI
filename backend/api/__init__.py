"""The HTTP layer, and the only part of the backend that imports FastAPI.

Everything below this package is plain Python: `backend.services` can be driven from a
script, a CLI or a test without a web server anywhere in the import graph.
"""

from .app import create_app

__all__ = ["create_app"]
