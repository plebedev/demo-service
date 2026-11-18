"""Domain-neutral Context Engine exceptions."""

from __future__ import annotations


class ArtifactIngestionError(ValueError):
    """Validation or extraction failure attributed to one artifact in a batch."""

    def __init__(self, index: int, message: str) -> None:
        super().__init__(message)
        self.index = index
        self.message = message


class IdempotencyConflictError(Exception):
    """An idempotency key was reused with a different request payload."""


class IdempotencyKeyExistsError(Exception):
    """A repository already holds an ingestion batch for an idempotency key."""
