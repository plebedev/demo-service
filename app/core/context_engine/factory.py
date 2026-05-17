"""Composition helpers for app-scoped Context Engine services."""

from __future__ import annotations

from fastapi import FastAPI

from app.core.config import Settings
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.service import ContextEngineService
from app.core.context_engine.sqlalchemy_storage import SQLAlchemyContextRepository
from app.db.session import get_session_factory


def build_domain_registry(settings: Settings) -> DomainRegistry:
    """Build the Context Engine domain registry for this process."""
    registry = DomainRegistry()
    from app.domains.job_search import build_job_search_domain_pack

    registry.register_domain(build_job_search_domain_pack())
    if settings.environment == "test":
        from app.domains.test_domain import build_test_domain_pack

        registry.register_domain(build_test_domain_pack())
    return registry


def attach_context_engine(app: FastAPI, settings: Settings) -> None:
    """Attach Context Engine infrastructure to the FastAPI app state."""
    registry = build_domain_registry(settings)
    repository = SQLAlchemyContextRepository(get_session_factory())
    app.state.context_domain_registry = registry
    app.state.context_repository = repository
    app.state.context_engine = ContextEngineService(
        registry=registry,
        repository=repository,
    )
