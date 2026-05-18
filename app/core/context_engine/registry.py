"""Domain pack registry for the Context Engine."""

from __future__ import annotations

from app.core.context_engine.interfaces import DomainPack, ViewDefinition
from app.core.context_engine.models import ArtifactType


class DomainRegistry:
    """In-memory registry of domain packs and extension metadata."""

    def __init__(self) -> None:
        self._domains: dict[str, DomainPack] = {}

    def register_domain(self, pack: DomainPack) -> None:
        """Register a domain pack by stable id."""
        if pack.id in self._domains:
            raise ValueError(f"Domain '{pack.id}' is already registered.")
        artifact_type_ids = [artifact_type.id for artifact_type in pack.artifact_types]
        if len(set(artifact_type_ids)) != len(artifact_type_ids):
            raise ValueError(f"Domain '{pack.id}' has duplicate artifact types.")
        view_ids = [view.id for view in pack.view_definitions]
        if len(set(view_ids)) != len(view_ids):
            raise ValueError(f"Domain '{pack.id}' has duplicate view definitions.")
        builder_ids = [builder.id for builder in pack.perspective_builders]
        if len(set(builder_ids)) != len(builder_ids):
            raise ValueError(f"Domain '{pack.id}' has duplicate perspective builders.")
        missing_view_ids = sorted(set(builder_ids) - set(view_ids))
        if missing_view_ids:
            raise ValueError(
                f"Domain '{pack.id}' has perspective builders without matching "
                f"view definitions: {', '.join(missing_view_ids)}."
            )
        self._domains[pack.id] = pack

    def get_domain(self, domain_id: str) -> DomainPack:
        """Return one registered domain pack."""
        try:
            return self._domains[domain_id]
        except KeyError as exc:
            raise KeyError(f"Domain '{domain_id}' is not registered.") from exc

    def list_domains(self) -> list[DomainPack]:
        """Return all registered domain packs in id order."""
        return [self._domains[key] for key in sorted(self._domains)]

    def list_artifact_types(self, domain_id: str) -> list[ArtifactType]:
        """Return artifact types for one domain pack."""
        return list(self.get_domain(domain_id).artifact_types)

    def list_perspectives(self, domain_id: str) -> list[str]:
        """Return registered perspective builder ids for one domain pack."""
        return [
            builder.id for builder in self.get_domain(domain_id).perspective_builders
        ]

    def list_views(self, domain_id: str) -> list[ViewDefinition]:
        """Return registered view definitions for one domain pack."""
        return list(self.get_domain(domain_id).view_definitions)
