"""Tests for SQLAlchemy Context Engine persistence behavior."""

from __future__ import annotations

import pytest

from app.core.context_engine.models import (
    Artifact,
    ContextSignal,
    OwnerType,
    PerspectiveView,
    SourceLink,
    ViewSection,
)
from app.core.context_engine.sqlalchemy_storage import SQLAlchemyContextRepository


def test_sqlalchemy_repository_rejects_source_link_less_signals(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)

    with pytest.raises(ValueError, match="must include source links"):
        repository.store_signals(
            [
                ContextSignal(
                    signal_type="missing_source",
                    label="Missing source",
                    value=True,
                )
            ]
        )


def test_sqlalchemy_repository_rejects_unknown_source_artifacts(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)

    with pytest.raises(ValueError, match="unknown source artifact"):
        repository.store_signals(
            [
                ContextSignal(
                    signal_type="unknown_source",
                    label="Unknown source",
                    value=True,
                    source_links=[SourceLink(artifact_id="missing-artifact")],
                )
            ]
        )


def test_sqlalchemy_repository_persists_source_grounded_signals(
    session_factory,
) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    artifact = repository.store_artifact(
        Artifact(
            domain_id="test-domain",
            artifact_type_id="note",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="owner-1",
            text="Grounded source",
        )
    )


def test_sqlalchemy_repository_persists_perspective_views(session_factory) -> None:
    repository = SQLAlchemyContextRepository(session_factory)
    artifact = repository.store_artifact(
        Artifact(
            domain_id="test-domain",
            artifact_type_id="note",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="owner-1",
            text="Perspective source",
        )
    )
    view = PerspectiveView(
        view_definition_id="test-summary",
        title="Test Summary",
        sections=[ViewSection(id="summary", title="Summary", content="Cached")],
    )

    stored = repository.store_perspective_view(
        view=view,
        domain_id="test-domain",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="owner-1",
        source_artifacts=[artifact],
    )
    loaded = repository.get_perspective_view(
        domain_id="test-domain",
        owner_type=OwnerType.INVITATION_CODE,
        owner_id="owner-1",
        view_definition_id="test-summary",
    )

    assert loaded is not None
    assert loaded.id == stored.id
    assert loaded.sections[0].content == "Cached"
    assert loaded.metadata["source_artifact_ids"] == [artifact.id]
    assert loaded.metadata["source_artifact_count"] == 1

    signals = repository.store_signals(
        [
            ContextSignal(
                signal_type="grounded",
                label="Grounded",
                value=True,
                source_links=[SourceLink(artifact_id=artifact.id)],
            )
        ]
    )

    assert signals[0].source_links[0].artifact_id == artifact.id
    assert (
        repository.list_signals(
            domain_id="test-domain",
            owner_type=OwnerType.INVITATION_CODE,
            owner_id="owner-1",
        )[0].id
        == signals[0].id
    )
