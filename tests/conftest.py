"""Pytest fixtures for backend API tests against a real Postgres database."""

from __future__ import annotations

from collections.abc import Generator, Iterator
import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

import app.db.models  # noqa: F401
from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory
from app.main import create_app


def _sqlalchemy_database_url(container: PostgresContainer) -> str:
    """Return a SQLAlchemy URL compatible with the repo's psycopg driver."""
    return container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+psycopg://"
    )


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    """Start a disposable Postgres container for migration and API tests."""
    container = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="demo_service",
        password="demo_service",
        dbname="demo_service",
    )
    container.start()

    yield container

    container.stop()


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> Iterator[str]:
    """Configure the app to use the ephemeral Postgres instance."""
    url = _sqlalchemy_database_url(postgres_container)

    previous_environment = {
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "ACCESS_TOKEN_SIGNING_KEY": os.environ.get("ACCESS_TOKEN_SIGNING_KEY"),
        "ACCESS_TOKEN_TTL_SECONDS": os.environ.get("ACCESS_TOKEN_TTL_SECONDS"),
        "ADMIN_API_SECRET": os.environ.get("ADMIN_API_SECRET"),
        "ENVIRONMENT": os.environ.get("ENVIRONMENT"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
        "SMS_NOTIFICATION_ENABLED": os.environ.get("SMS_NOTIFICATION_ENABLED"),
    }

    os.environ["DATABASE_URL"] = url
    os.environ["ACCESS_TOKEN_SIGNING_KEY"] = "test-signing-key"
    os.environ["ACCESS_TOKEN_TTL_SECONDS"] = "3600"
    os.environ["ADMIN_API_SECRET"] = "test-admin-secret"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["OPENAI_API_KEY"] = "test-openai-key"
    os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
    os.environ["SMS_NOTIFICATION_ENABLED"] = "true"

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")

    yield url

    for key, value in previous_environment.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    """Create a SQLAlchemy engine bound to the test Postgres container."""
    db_engine = create_engine(database_url, pool_pre_ping=True)

    yield db_engine

    db_engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a reusable ORM session factory for assertions and cleanup."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


@pytest.fixture(autouse=True)
def reset_database(
    session_factory: sessionmaker[Session],
) -> Generator[None, None, None]:
    """Truncate mutable tables between tests while preserving migrated schema."""
    session = session_factory()
    try:
        session.execute(
            text(
                """
                TRUNCATE TABLE
                    context_source_links,
                    context_perspective_views,
                    context_actionable_items,
                    context_signals,
                    context_relationships,
                    context_entities,
                    context_artifact_chunks,
                    context_artifacts,
                    rag_document_chunks,
                    rag_message_citations,
                    rag_messages,
                    rag_conversations,
                    rag_persona_documents,
                    rag_document_labels,
                    rag_personas,
                    rag_labels,
                    rag_documents,
                    sms_messages,
                    sms_conversations,
                    sms_opt_outs,
                    run_events,
                    runs,
                    invitation_requests,
                    invitation_redemptions,
                    invitation_codes,
                    voice_personas,
                    voice_experience_configs,
                    example_records
                RESTART IDENTITY CASCADE
                """
            )
        )
        session.commit()
        yield
    finally:
        session.close()


@pytest.fixture()
def db_session(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    """Provide a direct database session for assertions inside tests."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(database_url: str) -> Generator[TestClient, None, None]:
    """Create a test client that uses the migrated Postgres-backed app."""
    del database_url
    app = create_app()

    with TestClient(app) as test_client:
        yield test_client
