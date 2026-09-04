"""The save-library web app (optional extra: ``uv sync --extra web``)."""

from .app import ServerConfig, create_app, serve

__all__ = ["ServerConfig", "create_app", "serve"]
