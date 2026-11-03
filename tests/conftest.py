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
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

import app.db.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.main import create_app


def _sqlalchemy_database_url(container: PostgresContainer) -> str:
    """Return a SQLAlchemy URL compatible with the repo's psycopg driver."""
    return container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+psycopg://"
    )


def _configured_test_database_url() -> str | None:
    """Return and validate the explicitly configured local test database URL."""
    configured_url = os.environ.get("TEST_DATABASE_URL")
    if not configured_url:
        return None

    url = make_url(configured_url)
    database_name = url.database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(
            "TEST_DATABASE_URL must select a dedicated database whose name "
            "contains 'test'; the test suite truncates mutable tables."
        )
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("TEST_DATABASE_URL must use PostgreSQL.")
    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


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
def database_url(request: pytest.FixtureRequest) -> Iterator[str]:
    """Configure the app to use local Postgres or a disposable container."""
    url = _configured_test_database_url()
    if url is None:
        postgres_container = request.getfixturevalue("postgres_container")
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
    """Create a SQLAlchemy engine bound to the selected test database."""
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
        preparer = session.get_bind().dialect.identifier_preparer
        table_names = ", ".join(
            preparer.format_table(table) for table in Base.metadata.sorted_tables
        )
        session.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
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
