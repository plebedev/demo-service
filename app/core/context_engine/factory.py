"""Composition helpers for app-scoped Context Engine services."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.core.config import Settings
from app.core.context_engine.llm import (
    ContextExecutionContext,
    ContextExecutionMode,
    PydanticAIContextModelRunner,
    load_context_model_flow_catalog,
)
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
        execution_context=_build_execution_context(settings),
    )


def _build_execution_context(settings: Settings) -> ContextExecutionContext | None:
    """Build generic Context Engine model execution helpers."""
    try:
        catalog = load_context_model_flow_catalog(
            settings.context_engine_model_config_path
        )
    except ValueError:
        if settings.environment == "test":
            return None
        raise
    return ContextExecutionContext(
        catalog=catalog,
        runner=PydanticAIContextModelRunner(settings),
        prompt_root=DOMAIN_PROMPT_ROOT,
        mode_override=ContextExecutionMode(settings.context_engine_execution_mode),
    )


DOMAIN_PROMPT_ROOT = Path("app/domains")
