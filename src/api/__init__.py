"""FastAPI application package for Delaxis.

The ASGI app lives in ``src.api.main`` (uvicorn target: ``src.api.main:app``).
This package intentionally avoids re-exporting it so that importing submodules
(e.g. ``src.api.context``) does not construct the whole application.
"""
