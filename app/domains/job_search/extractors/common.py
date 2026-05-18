"""Rule-based extraction helpers for the Job Search domain pack."""

from __future__ import annotations

import re

from app.core.context_engine.models import (
    ActionableItem,
    ContextEntity,
    ContextSignal,
    ReadinessStatus,
    SourceLink,
)
from app.domains.job_search.models import ExtractedValue


TECH_KEYWORDS = [
    "Python",
    "TypeScript",
    "React",
    "Next.js",
    "FastAPI",
    "SQLAlchemy",
    "Oracle",
    "Postgres",
    "Kubernetes",
    "Docker",
    "Terraform",
    "AWS",
    "GCP",
    "OCI",
    "LangChain",
    "OpenAI",
    "Anthropic",
    "RAG",
    "agents",
    "embeddings",
]


def signal(
    signal_type: str,
    label: str,
    value: str | int | float | bool | None,
    source_link: SourceLink,
    **metadata: object,
) -> ContextSignal:
    """Create a source-grounded generic signal."""
    return ContextSignal(
        signal_type=signal_type,
        label=label,
        value=value,
        source_links=[source_link],
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def entity(
    entity_type: str,
    name: str,
    source_link: SourceLink,
    **metadata: object,
) -> ContextEntity:
    """Create a source-grounded generic entity."""
    return ContextEntity(
        entity_type=entity_type,
        name=name,
        source_links=[source_link],
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def action(
    item_type: str,
    title: str,
    source_link: SourceLink,
    *,
    description: str | None = None,
    readiness_status: ReadinessStatus = ReadinessStatus.NEEDS_REVIEW,
    **metadata: object,
) -> ActionableItem:
    """Create a source-grounded generic actionable item."""
    return ActionableItem(
        item_type=item_type,
        title=title,
        description=description,
        readiness_status=readiness_status,
        source_links=[source_link],
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def signals_from_values(
    signal_type: str,
    label: str,
    values: list[ExtractedValue],
) -> list[ContextSignal]:
    """Convert extracted values to signals."""
    return [
        signal(signal_type, label, value.value, value.source_link) for value in values
    ]


def infer_seniority(text: str) -> str | None:
    """Infer seniority from common role-language markers."""
    lowered = text.lower()
    if re.search(r"\b(staff|principal|architect)\b", lowered):
        return "staff_or_principal"
    if re.search(r"\b(senior|lead)\b", lowered):
        return "senior_or_lead"
    if re.search(r"\b(manager|director|head of)\b", lowered):
        return "management"
    if re.search(r"\b(junior|associate|entry)\b", lowered):
        return "early_career"
    return None
