"""SQLAlchemy engine and session helpers for request-scoped database access."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create and cache the SQLAlchemy engine for the process."""
    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url,
        connect_args=settings.sqlalchemy_connect_args,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create and cache the SQLAlchemy session factory."""
    return sessionmaker(
        bind=get_engine(), autoflush=False, autocommit=False, class_=Session
    )


def get_db_session() -> Generator[Session, None, None]:
    """Yield a database session and close it after the request finishes."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
