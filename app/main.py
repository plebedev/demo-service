"""FastAPI application factory for the backend service."""

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.context_engine.factory import attach_context_engine
from app.core.logging import configure_logging
from app.workflows.loader import attach_workflow_registry


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    attach_context_engine(app, settings)
    attach_workflow_registry(app, settings)
    app.include_router(api_router)
    return app
