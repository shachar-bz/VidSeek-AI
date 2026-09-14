"""Cross-cutting foundations shared by every backend service.

Nothing here may import from `backend.services` or `backend.api`: this is the bottom of
the dependency hierarchy, and it depends on the standard library and python-dotenv alone.
"""
