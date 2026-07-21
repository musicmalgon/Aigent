"""ASGI entrypoint for the Re:Mind AI service."""

from .api import create_app


app = create_app()


__all__ = ["app"]
