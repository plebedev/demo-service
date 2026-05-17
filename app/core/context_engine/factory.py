"""Composition helpers for app-scoped Context Engine services."""

from __future__ import annotations

from fastapi import FastAPI

from app.core.config import Settings
from app.core.context_engine.registry import DomainRegistry
from app.core.context_engine.service import ContextEngineService
from app.core.context_engine.storage import InMemoryContextRepository


def build_domain_registry(settings: Settings) -> DomainRegistry:
    """Build the Context Engine domain registry for this process."""
    registry = DomainRegistry()
    if settings.environment == "test":
        from app.domains.test_domain import build_test_domain_pack

        registry.register_domain(build_test_domain_pack())
    return registry


def attach_context_engine(app: FastAPI, settings: Settings) -> None:
    """Attach Context Engine infrastructure to the FastAPI app state."""
    registry = build_domain_registry(settings)
    repository = InMemoryContextRepository()
    app.state.context_domain_registry = registry
    app.state.context_repository = repository
    app.state.context_engine = ContextEngineService(
        registry=registry,
        repository=repository,
    )
