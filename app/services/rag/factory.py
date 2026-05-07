"""Composition helpers for binding environment-specific RAG strategies."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.embeddings import build_embedding_provider
from app.services.rag.local_postgres import LocalPostgresRagStrategy
from app.services.rag.oracle_native import OracleNativeRagStrategy
from app.services.rag.strategy import RagService


def build_rag_service(session: Session, settings: Settings) -> RagService:
    """Bind the RAG service implementation for the active database backend."""
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "oracle":
        return RagService(OracleNativeRagStrategy())
    if dialect_name == "postgresql":
        return RagService(
            LocalPostgresRagStrategy(embeddings=build_embedding_provider(settings))
        )
    raise RuntimeError(f"Unsupported database dialect for RAG: {dialect_name}.")
