"""Pytest fixtures for backend API tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session, get_engine, get_session_factory
from app.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    """Create a test client backed by a temporary SQLite database."""
    database_path = tmp_path / "test.db"
    database_url = f"sqlite+pysqlite:///{database_path}"

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ACCESS_TOKEN_SIGNING_KEY", "test-signing-key")
    monkeypatch.setenv("ACCESS_TOKEN_TTL_SECONDS", "3600")
    monkeypatch.setenv("ADMIN_API_SECRET", "test-admin-secret")

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    testing_session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )
    Base.metadata.create_all(bind=engine)

    app = create_app()

    def override_db_session() -> Generator[Session, None, None]:
        session = testing_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db_session

    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
