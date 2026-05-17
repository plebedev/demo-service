"""Tests for Context Engine domain registration."""

from __future__ import annotations

import pytest

from app.core.context_engine.registry import DomainRegistry
from app.domains.test_domain import build_test_domain_pack


def test_domain_registration_lists_extensions() -> None:
    registry = DomainRegistry()
    pack = build_test_domain_pack()

    registry.register_domain(pack)

    assert registry.get_domain("test-domain") is pack
    assert [domain.id for domain in registry.list_domains()] == ["test-domain"]
    assert [item.id for item in registry.list_artifact_types("test-domain")] == ["note"]
    assert registry.list_perspectives("test-domain") == ["test-perspective-builder"]
    assert [view.id for view in registry.list_views("test-domain")] == ["test-summary"]


def test_domain_registration_rejects_duplicate_domain() -> None:
    registry = DomainRegistry()
    registry.register_domain(build_test_domain_pack())

    with pytest.raises(ValueError, match="already registered"):
        registry.register_domain(build_test_domain_pack())


def test_invalid_domain_lookup_is_rejected() -> None:
    registry = DomainRegistry()

    with pytest.raises(KeyError, match="not registered"):
        registry.get_domain("missing-domain")
