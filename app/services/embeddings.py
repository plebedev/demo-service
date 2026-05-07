"""Embedding providers for local RAG ingestion and search."""

from __future__ import annotations

import json
from typing import Protocol
from urllib import error, request

from app.core.config import Settings
from app.services.rag_store import EMBEDDING_DIMENSIONS


class EmbeddingProvider(Protocol):
    """Small interface for converting text into fixed-size vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input text."""


class OllamaEmbeddingProvider:
    """Embedding provider backed by a local Ollama server."""

    def __init__(self, *, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Call Ollama's embedding endpoint and validate the response shape."""
        if not texts:
            return []

        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=120) as response:
                raw_response = response.read()
        except error.URLError as exc:
            raise RuntimeError(
                f"Could not reach Ollama embedding service at {self.base_url}."
            ) from exc

        decoded = json.loads(raw_response.decode("utf-8"))
        embeddings = decoded.get("embeddings")
        if not isinstance(embeddings, list):
            raise RuntimeError("Ollama embedding response did not include embeddings.")
        if len(embeddings) != len(texts):
            raise RuntimeError(
                "Ollama returned a different number of embeddings than requested."
            )

        return [self._coerce_embedding(item) for item in embeddings]

    def _coerce_embedding(self, value: object) -> list[float]:
        if not isinstance(value, list):
            raise RuntimeError("Ollama returned a malformed embedding.")
        embedding = [float(item) for item in value]
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"Ollama model {self.model} returned {len(embedding)} dimensions; "
                f"expected {EMBEDDING_DIMENSIONS}."
            )
        return embedding


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Build the configured embedding provider."""
    if settings.rag_embedding_provider != "ollama":
        raise RuntimeError(
            f"Unsupported RAG embedding provider: {settings.rag_embedding_provider}."
        )
    return OllamaEmbeddingProvider(
        base_url=settings.rag_ollama_base_url,
        model=settings.rag_embedding_model,
    )
