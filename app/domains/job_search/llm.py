"""LLM-assisted job_search domain adapters."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.core.context_engine.interfaces import (
    Extractor,
    PerspectiveBuilder,
    TaskGenerator,
)
from app.core.context_engine.llm import (
    ContextExecutionContext,
    ContextExecutionMode,
    ResolvedContextModelStep,
    metadata_for_generated_step,
)
from app.core.context_engine.models import (
    ActionableItem,
    Artifact,
    ArtifactChunk,
    ContextEntity,
    ContextRelationship,
    ContextSignal,
    EvidenceLink,
    ExtractionResult,
    PerspectiveBuildContext,
    PerspectiveView,
    ReadinessStatus,
    SourceLink,
    ViewSection,
)

ConfidenceLabel = Literal["low", "medium", "high"]
EvidenceKind = Literal["explicit", "inferred"]
logger = logging.getLogger(__name__)


class PerspectiveContextLimits(BaseModel):
    """Token and item limits for one perspective context graph."""

    model_config = ConfigDict(extra="forbid")

    chunks: int = Field(default=18, ge=1)
    signals: int = Field(default=24, ge=0)
    actionable_items: int = Field(default=6, ge=0)
    chunk_chars: int = Field(default=900, ge=1)
    source_excerpt_chars: int = Field(default=300, ge=1)


class PerspectiveContextNode(BaseModel):
    """One node in a declarative perspective context graph."""

    model_config = ConfigDict(extra="forbid")

    types: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    fallback_artifact_types: list[str] = Field(default_factory=list)


class PerspectiveContextGraph(BaseModel):
    """Declarative context dependencies for one perspective."""

    model_config = ConfigDict(extra="forbid")

    limits: PerspectiveContextLimits = Field(default_factory=PerspectiveContextLimits)
    nodes: dict[str, PerspectiveContextNode] = Field(default_factory=dict)

    def node(self, name: str) -> PerspectiveContextNode:
        """Return a configured node or an empty node."""
        return self.nodes.get(name, PerspectiveContextNode())

    def require_node_types(self, name: str) -> None:
        """Fail clearly when a selection node is missing explicit types."""
        if not self.node(name).types:
            raise ValueError(
                f"Perspective context graph node '{name}' must declare explicit types."
            )


class LLMSourceReference(BaseModel):
    """Structured reference to provided source material."""

    chunk_id: str
    excerpt: str = Field(min_length=1)
    label: str | None = None


class LLMContextEntity(BaseModel):
    """Model-generated entity candidate."""

    entity_type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    explicit_or_inferred: EvidenceKind
    confidence: ConfidenceLabel
    source_references: list[LLMSourceReference] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class LLMContextSignal(BaseModel):
    """Model-generated signal candidate."""

    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    signal_type: str = Field(min_length=1)
    explicit_or_inferred: EvidenceKind
    confidence: ConfidenceLabel
    source_references: list[LLMSourceReference] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class LLMContextRelationship(BaseModel):
    """Model-generated relationship candidate."""

    relationship_type: str = Field(min_length=1)
    source_entity_name: str = Field(min_length=1)
    target_entity_name: str = Field(min_length=1)
    explicit_or_inferred: EvidenceKind
    confidence: ConfidenceLabel
    source_references: list[LLMSourceReference] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class LLMActionableItem(BaseModel):
    """Model-generated actionable item."""

    item_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    priority: Literal["low", "medium", "high"]
    readiness_status: ReadinessStatus
    owner_type: Literal["human", "agent", "shared"]
    rationale: str = Field(min_length=1)
    evidence_links: list[LLMSourceReference] = Field(min_length=1)


class LLMExtractionOutput(BaseModel):
    """Structured artifact extraction output."""

    model_config = ConfigDict(extra="forbid")

    entities: list[LLMContextEntity] = Field(default_factory=list)
    signals: list[LLMContextSignal] = Field(default_factory=list)
    relationships: list[LLMContextRelationship] = Field(default_factory=list)
    actionable_items: list[LLMActionableItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LLMPerspectiveSection(BaseModel):
    """Model-generated perspective section."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    synthesized_conclusion: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    confidence: ConfidenceLabel
    evidence_references: list[LLMSourceReference] = Field(min_length=1)
    actionable_implications: list[str] = Field(default_factory=list)
    explicit_or_inferred: EvidenceKind
    rationale: str = Field(min_length=1)


class LLMPerspectiveOutput(BaseModel):
    """Structured perspective synthesis output."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    sections: list[LLMPerspectiveSection] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class LLMActionableItemOutput(BaseModel):
    """Structured actionable-item synthesis output."""

    model_config = ConfigDict(extra="forbid")

    actionable_items: list[LLMActionableItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class LLMAssistedExtractor:
    """Wrap a deterministic extractor with optional LLM-assisted extraction."""

    base: Extractor

    @property
    def id(self) -> str:
        """Return the wrapped extractor id."""
        return str(getattr(self.base, "id"))

    @property
    def artifact_type_ids(self) -> tuple[str, ...] | None:
        """Return the wrapped extractor artifact dispatch hints."""
        artifact_type_ids = getattr(self.base, "artifact_type_ids", None)
        return cast(tuple[str, ...] | None, artifact_type_ids)

    def extract(
        self, artifact: Artifact, chunks: list[ArtifactChunk]
    ) -> ExtractionResult:
        """Run the deterministic wrapped extractor."""
        return self.base.extract(artifact, chunks)

    def extract_with_execution(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
        execution_context: ContextExecutionContext | None,
    ) -> ExtractionResult:
        """Run deterministic extraction with optional LLM-assisted additions."""
        deterministic = self.extract(artifact, chunks)
        _mark_deterministic_extraction(deterministic)
        if execution_context is None:
            return _with_fallback_warning(deterministic, "llm_execution_not_configured")
        try:
            step = execution_context.resolve_step(
                domain_id=artifact.domain_id,
                flow_id="extraction",
                step_id="artifact_extraction",
                purpose="structured_extraction",
            )
            if step.mode == ContextExecutionMode.DETERMINISTIC:
                return deterministic
            output = execution_context.run_structured(
                step=step,
                instructions=execution_context.load_prompt(step),
                prompt=_artifact_extraction_prompt(artifact, chunks),
                output_type=LLMExtractionOutput,
            )
            llm_result = _map_extraction_output(output, artifact, chunks, step)
        except Exception as exc:
            return _with_fallback_warning(deterministic, f"llm_failed: {exc}")
        if step.mode == ContextExecutionMode.LLM:
            return llm_result if _has_outputs(llm_result) else deterministic
        return ExtractionResult(
            entities=deterministic.entities + llm_result.entities,
            relationships=deterministic.relationships + llm_result.relationships,
            signals=deterministic.signals + llm_result.signals,
            actionable_items=deterministic.actionable_items
            + llm_result.actionable_items,
            metadata={
                **deterministic.metadata,
                "llm_mode": step.mode.value,
                "llm_warnings": output.warnings,
            },
        )


@dataclass(frozen=True)
class LLMAssistedPerspectiveBuilder:
    """Wrap a deterministic perspective builder with optional LLM synthesis."""

    base: PerspectiveBuilder
    context_graph: PerspectiveContextGraph = field(
        default_factory=PerspectiveContextGraph
    )

    @property
    def id(self) -> str:
        """Return the wrapped perspective builder id."""
        return str(getattr(self.base, "id"))

    def build(self, context: PerspectiveBuildContext) -> PerspectiveView:
        """Run the deterministic wrapped perspective builder."""
        return self.base.build(context)

    def build_with_execution(
        self,
        context: PerspectiveBuildContext,
        execution_context: ContextExecutionContext | None,
    ) -> PerspectiveView:
        """Build a perspective with optional LLM-assisted synthesis."""
        deterministic = self.build(context)
        _mark_deterministic_view(deterministic)
        if execution_context is None:
            deterministic.metadata["fallback_warning"] = "llm_execution_not_configured"
            return deterministic
        try:
            step = execution_context.resolve_step(
                domain_id=context.domain_id,
                flow_id="perspective_synthesis",
                step_id=self.id,
                purpose="perspective_synthesis",
            )
            if step.mode == ContextExecutionMode.DETERMINISTIC:
                return deterministic
            prompt, prompt_ids = _perspective_prompt(
                context, deterministic, self.context_graph
            )
            output = execution_context.run_structured(
                step=step,
                instructions=execution_context.load_prompt(step),
                prompt=prompt,
                output_type=LLMPerspectiveOutput,
            )
            synthesized = _map_perspective_output(
                output, context, step, self.id, prompt_ids
            )
        except Exception as exc:
            deterministic.metadata["fallback_warning"] = f"llm_failed: {exc}"
            return deterministic
        if step.mode == ContextExecutionMode.LLM:
            return synthesized
        synthesized.metadata["deterministic_section_count"] = len(
            deterministic.sections
        )
        return synthesized


@dataclass(frozen=True)
class LLMAssistedTaskGenerator:
    """Wrap deterministic task generation with optional LLM refinement."""

    base: TaskGenerator

    @property
    def id(self) -> str:
        """Return the wrapped task generator id."""
        return str(getattr(self.base, "id"))

    def generate(self, artifact: Artifact) -> list[ActionableItem]:
        """Run the deterministic wrapped task generator."""
        return self.base.generate(artifact)

    def generate_with_execution(
        self,
        artifact: Artifact,
        chunks: list[ArtifactChunk],
        current_items: list[ActionableItem],
        execution_context: ContextExecutionContext | None,
    ) -> list[ActionableItem]:
        """Generate deterministic tasks with optional LLM refinement."""
        deterministic = self.generate(artifact)
        for item in deterministic:
            item.metadata.setdefault("generated_by", "deterministic")
            item.metadata.setdefault("explicit_or_inferred", "inferred")
        items = current_items + deterministic
        if execution_context is None:
            for item in deterministic:
                item.metadata["fallback_warning"] = "llm_execution_not_configured"
            return items
        try:
            step = execution_context.resolve_step(
                domain_id=artifact.domain_id,
                flow_id="actionable_item_synthesis",
                step_id="actionable_items",
                purpose="actionable_item_synthesis",
            )
            if step.mode == ContextExecutionMode.DETERMINISTIC:
                return items
            output = execution_context.run_structured(
                step=step,
                instructions=execution_context.load_prompt(step),
                prompt=_actionable_item_prompt(artifact, chunks, items),
                output_type=LLMActionableItemOutput,
            )
            llm_items = _map_actionable_items(
                output.actionable_items, chunks, artifact, step
            )
        except Exception as exc:
            for item in deterministic:
                item.metadata["fallback_warning"] = f"llm_failed: {exc}"
            return items
        if step.mode == ContextExecutionMode.LLM:
            return current_items + (llm_items or deterministic)
        return items + llm_items


def _mark_deterministic_extraction(result: ExtractionResult) -> None:
    for entity in result.entities:
        entity.metadata.setdefault("generated_by", "deterministic")
        entity.metadata.setdefault("explicit_or_inferred", "explicit")
    for relationship in result.relationships:
        relationship.metadata.setdefault("generated_by", "deterministic")
        relationship.metadata.setdefault("explicit_or_inferred", "explicit")
    for signal in result.signals:
        signal.metadata.setdefault("generated_by", "deterministic")
        signal.metadata.setdefault(
            "explicit_or_inferred",
            "inferred" if signal.metadata.get("reason") else "explicit",
        )
    for item in result.actionable_items:
        item.metadata.setdefault("generated_by", "deterministic")
        item.metadata.setdefault("explicit_or_inferred", "inferred")


def _mark_deterministic_view(view: PerspectiveView) -> None:
    view.metadata.setdefault("generated_by", "deterministic")
    for section in view.sections:
        section.metadata.setdefault("generated_by", "deterministic")


def _with_fallback_warning(result: ExtractionResult, warning: str) -> ExtractionResult:
    result.metadata.setdefault("fallback_warning", warning)
    for signal in result.signals:
        signal.metadata.setdefault("fallback_warning", warning)
    for item in result.actionable_items:
        item.metadata.setdefault("fallback_warning", warning)
    return result


def _has_outputs(result: ExtractionResult) -> bool:
    return bool(
        result.entities
        or result.relationships
        or result.signals
        or result.actionable_items
    )


def _source_link(
    reference: LLMSourceReference,
    chunks_by_id: dict[str, ArtifactChunk],
    artifact: Artifact,
) -> SourceLink:
    chunk = chunks_by_id.get(reference.chunk_id)
    if chunk is None:
        raise ValueError(f"Unknown source chunk '{reference.chunk_id}'.")
    if not reference.excerpt.strip():
        raise ValueError("LLM source reference excerpt cannot be empty.")
    return SourceLink(
        artifact_id=artifact.id,
        chunk_id=chunk.id,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        label=reference.label or artifact.artifact_type_id,
        excerpt=reference.excerpt.strip()[:1000],
    )


def _source_links(
    references: list[LLMSourceReference],
    chunks: list[ArtifactChunk],
    artifact: Artifact,
) -> list[SourceLink]:
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    links = [
        _source_link(reference, chunks_by_id, artifact) for reference in references
    ]
    if not links:
        raise ValueError("LLM output must include source references.")
    return links


def _map_extraction_output(
    output: LLMExtractionOutput,
    artifact: Artifact,
    chunks: list[ArtifactChunk],
    step: ResolvedContextModelStep,
) -> ExtractionResult:
    metadata = metadata_for_generated_step(step)
    warnings = list(output.warnings)
    entities: list[ContextEntity] = []
    entity_ids_by_name: dict[str, str] = {}
    for item in output.entities:
        entity = ContextEntity(
            entity_type=item.entity_type,
            name=item.name,
            source_links=_source_links(item.source_references, chunks, artifact),
            metadata={
                **metadata,
                "explicit_or_inferred": item.explicit_or_inferred,
                "confidence": item.confidence,
                "rationale": item.rationale,
            },
        )
        entities.append(entity)
        entity_ids_by_name[_normalize_entity_name(item.name)] = entity.id
    signals = [
        ContextSignal(
            signal_type=item.signal_type,
            label=item.title,
            value=item.summary,
            source_links=_source_links(item.source_references, chunks, artifact),
            metadata={
                **metadata,
                "summary": item.summary,
                "explicit_or_inferred": item.explicit_or_inferred,
                "confidence": item.confidence,
                "rationale": item.rationale,
            },
        )
        for item in output.signals
    ]
    relationships = []
    for relationship_item in output.relationships:
        source_entity_id = entity_ids_by_name.get(
            _normalize_entity_name(relationship_item.source_entity_name)
        )
        target_entity_id = entity_ids_by_name.get(
            _normalize_entity_name(relationship_item.target_entity_name)
        )
        if source_entity_id is None or target_entity_id is None:
            warnings.append(
                "Dropped relationship with unresolved entity names: "
                f"{relationship_item.source_entity_name!r} -> "
                f"{relationship_item.target_entity_name!r}."
            )
            continue
        relationships.append(
            ContextRelationship(
                relationship_type=relationship_item.relationship_type,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                source_links=_source_links(
                    relationship_item.source_references, chunks, artifact
                ),
                metadata={
                    **metadata,
                    "source_entity_name": relationship_item.source_entity_name,
                    "target_entity_name": relationship_item.target_entity_name,
                    "explicit_or_inferred": relationship_item.explicit_or_inferred,
                    "confidence": relationship_item.confidence,
                    "rationale": relationship_item.rationale,
                },
            )
        )
    actionable_items = _map_actionable_items(
        output.actionable_items, chunks, artifact, step
    )
    return ExtractionResult(
        entities=entities,
        relationships=relationships,
        signals=signals,
        actionable_items=actionable_items,
        metadata={"generated_by": "llm", "warnings": warnings},
    )


def _map_actionable_items(
    items: list[LLMActionableItem],
    chunks: list[ArtifactChunk],
    artifact: Artifact,
    step: ResolvedContextModelStep,
) -> list[ActionableItem]:
    metadata = metadata_for_generated_step(step)
    return [
        ActionableItem(
            item_type=item.item_type,
            title=item.title,
            description=item.description,
            readiness_status=item.readiness_status,
            source_links=_source_links(item.evidence_links, chunks, artifact),
            metadata={
                **metadata,
                "priority": item.priority,
                "owner_type": item.owner_type,
                "rationale": item.rationale,
                "explicit_or_inferred": "inferred",
                "confidence": "medium",
            },
        )
        for item in items
    ]


def _map_perspective_output(
    output: LLMPerspectiveOutput,
    context: PerspectiveBuildContext,
    step: ResolvedContextModelStep,
    view_definition_id: str,
    prompt_ids: "_PromptIdMap",
) -> PerspectiveView:
    chunks_by_id = {
        prompt_ids.original_chunk_id(chunk.id): chunk for chunk in context.chunks
    }
    artifacts_by_id = {artifact.id: artifact for artifact in context.artifacts}
    metadata = metadata_for_generated_step(step)
    sections = []
    for section in output.sections:
        evidence = []
        for reference in section.evidence_references:
            original_chunk_id = prompt_ids.original_chunk_id(reference.chunk_id)
            chunk = chunks_by_id.get(original_chunk_id)
            if chunk is None:
                raise ValueError(f"Unknown source chunk '{reference.chunk_id}'.")
            artifact = artifacts_by_id.get(chunk.artifact_id)
            if artifact is None:
                raise ValueError(f"Unknown source artifact '{chunk.artifact_id}'.")
            source = _source_link(
                LLMSourceReference(
                    chunk_id=original_chunk_id,
                    excerpt=reference.excerpt,
                    label=reference.label,
                ),
                chunks_by_id,
                artifact,
            )
            evidence.append(
                EvidenceLink(
                    source=source,
                    confidence=_confidence_score(section.confidence),
                    note=f"{section.title} ({section.explicit_or_inferred})",
                )
            )
        content_parts = [
            section.synthesized_conclusion,
            f"Why it matters: {section.why_it_matters}",
        ]
        content_parts.extend(
            f"Implication: {implication}"
            for implication in section.actionable_implications
        )
        sections.append(
            ViewSection(
                id=section.id,
                title=section.title,
                content="\n".join(content_parts),
                evidence_links=evidence,
                metadata={
                    **metadata,
                    "confidence": section.confidence,
                    "explicit_or_inferred": section.explicit_or_inferred,
                    "rationale": section.rationale,
                    "actionable_implications": section.actionable_implications,
                    "evidence_kinds": [section.explicit_or_inferred],
                },
            )
        )
    return PerspectiveView(
        view_definition_id=view_definition_id,
        title=output.title,
        sections=sections,
        metadata={**metadata, "warnings": output.warnings},
    )


def _confidence_score(label: ConfidenceLabel) -> float:
    return {"low": 0.35, "medium": 0.65, "high": 0.9}[label]


def _artifact_extraction_prompt(artifact: Artifact, chunks: list[ArtifactChunk]) -> str:
    return json.dumps(
        {
            "artifact": artifact.model_dump(mode="json"),
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
        },
        indent=2,
        sort_keys=True,
    )


def _perspective_prompt(
    context: PerspectiveBuildContext,
    deterministic: PerspectiveView,
    context_graph: PerspectiveContextGraph,
) -> tuple[str, "_PromptIdMap"]:
    prompt_ids = _PromptIdMap()
    selected_chunks = _select_perspective_chunks(context, deterministic, context_graph)
    selected_chunk_ids = {chunk.id for chunk in selected_chunks}
    selected_artifact_ids = {chunk.artifact_id for chunk in selected_chunks}
    selected_signals = [
        signal
        for signal in _select_perspective_signals(context, context_graph)
        if _has_selected_source(
            signal.source_links, selected_chunk_ids, selected_artifact_ids
        )
    ][: context_graph.limits.signals]
    selected_items = [
        item
        for item in _select_perspective_actionable_items(context, context_graph)
        if _has_selected_source(
            item.source_links, selected_chunk_ids, selected_artifact_ids
        )
    ][: context_graph.limits.actionable_items]
    prompt = json.dumps(
        {
            "perspective_id": deterministic.view_definition_id,
            "instructions": {
                "source_reference_rule": (
                    "Use chunk ids exactly as provided. They are compact ids for "
                    "this request and will be remapped after validation."
                ),
                "max_sections": 5,
                "max_evidence_references_per_section": 3,
                "max_actionable_implications_per_section": 3,
            },
            "deterministic_view": _compact_view(
                deterministic, prompt_ids, context_graph.limits
            ),
            "artifacts": [
                _compact_artifact(artifact, prompt_ids)
                for artifact in _artifacts_for_chunks(
                    context.artifacts, selected_chunks
                )
            ],
            "chunks": [
                _compact_chunk(chunk, prompt_ids, context_graph.limits)
                for chunk in selected_chunks
            ],
            "signals": [
                _compact_signal(signal, prompt_ids, context_graph.limits)
                for signal in selected_signals
            ],
            "actionable_items": [
                _compact_actionable_item(item, prompt_ids, context_graph.limits)
                for item in selected_items
            ],
        },
        indent=2,
        sort_keys=True,
    )
    return prompt, prompt_ids


def _actionable_item_prompt(
    artifact: Artifact,
    chunks: list[ArtifactChunk],
    current_items: list[ActionableItem],
) -> str:
    return json.dumps(
        {
            "artifact": artifact.model_dump(mode="json"),
            "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            "current_actionable_items": [
                item.model_dump(mode="json") for item in current_items
            ],
        },
        indent=2,
        sort_keys=True,
    )


@dataclass
class _PromptIdMap:
    """Compact long persisted ids before sending them to a model."""

    artifact_ids: dict[str, str] = field(default_factory=dict)
    chunk_ids: dict[str, str] = field(default_factory=dict)
    signal_ids: dict[str, str] = field(default_factory=dict)
    item_ids: dict[str, str] = field(default_factory=dict)

    def artifact_id(self, original: str) -> str:
        """Return compact artifact id for this prompt."""
        return self._compact(self.artifact_ids, original, "a")

    def chunk_id(self, original: str) -> str:
        """Return compact chunk id for this prompt."""
        return self._compact(self.chunk_ids, original, "c")

    def signal_id(self, original: str) -> str:
        """Return compact signal id for this prompt."""
        return self._compact(self.signal_ids, original, "s")

    def item_id(self, original: str) -> str:
        """Return compact actionable item id for this prompt."""
        return self._compact(self.item_ids, original, "i")

    def original_chunk_id(self, compact_or_original: str) -> str:
        """Return original chunk id for a model-returned reference."""
        for original, compact in self.chunk_ids.items():
            if compact == compact_or_original:
                return original
        return compact_or_original

    @staticmethod
    def _compact(mapping: dict[str, str], original: str, prefix: str) -> str:
        if original not in mapping:
            mapping[original] = f"{prefix}{len(mapping) + 1}"
        return mapping[original]


def _select_perspective_chunks(
    context: PerspectiveBuildContext,
    deterministic: PerspectiveView,
    context_graph: PerspectiveContextGraph,
) -> list[ArtifactChunk]:
    """Return bounded chunks relevant to a single perspective."""
    chunks_by_id = {chunk.id: chunk for chunk in context.chunks}
    chunks_node = context_graph.node("chunks")
    selected_ids: list[str] = []
    if "deterministic_view" in chunks_node.depends_on:
        for section in deterministic.sections:
            for evidence in section.evidence_links:
                if evidence.source.chunk_id:
                    selected_ids.append(evidence.source.chunk_id)
    if "signals" in chunks_node.depends_on:
        for signal in _select_perspective_signals(context, context_graph):
            for link in signal.source_links:
                if link.chunk_id:
                    selected_ids.append(link.chunk_id)
    if "actionable_items" in chunks_node.depends_on:
        for item in _select_perspective_actionable_items(context, context_graph):
            for link in item.source_links:
                if link.chunk_id:
                    selected_ids.append(link.chunk_id)
    selected = _dedupe_chunks(
        chunks_by_id[chunk_id] for chunk_id in selected_ids if chunk_id in chunks_by_id
    )
    if len(selected) < context_graph.limits.chunks:
        fallback_artifact_types = (
            chunks_node.fallback_artifact_types or context_graph.node("artifacts").types
        )
        selected.extend(
            chunk
            for chunk in context.chunks
            if chunk not in selected
            and _artifact_type_for_chunk(context, chunk) in fallback_artifact_types
        )
    return _dedupe_chunks(selected)[: context_graph.limits.chunks]


def _select_perspective_signals(
    context: PerspectiveBuildContext, context_graph: PerspectiveContextGraph
) -> list[ContextSignal]:
    """Return signals relevant to a single job_search perspective."""
    configured_types = set(context_graph.node("signals").types)
    if not configured_types:
        logger.warning("Perspective context graph has no signal types configured.")
        return []
    return [
        signal for signal in context.signals if signal.signal_type in configured_types
    ]


def _select_perspective_actionable_items(
    context: PerspectiveBuildContext, context_graph: PerspectiveContextGraph
) -> list[ActionableItem]:
    """Return actionable items relevant to a single job_search perspective."""
    configured_types = set(context_graph.node("actionable_items").types)
    if not configured_types:
        logger.warning(
            "Perspective context graph has no actionable item types configured."
        )
        return []
    return [
        item for item in context.actionable_items if item.item_type in configured_types
    ]


def _has_selected_source(
    source_links: list[SourceLink],
    selected_chunk_ids: set[str],
    selected_artifact_ids: set[str],
) -> bool:
    """Return whether a context item is grounded in selected context."""
    return any(
        link.chunk_id in selected_chunk_ids or link.artifact_id in selected_artifact_ids
        for link in source_links
    )


def _artifact_type_for_chunk(
    context: PerspectiveBuildContext, chunk: ArtifactChunk
) -> str | None:
    artifacts_by_id = {artifact.id: artifact for artifact in context.artifacts}
    artifact = artifacts_by_id.get(chunk.artifact_id)
    return artifact.artifact_type_id if artifact else None


def _artifacts_for_chunks(
    artifacts: list[Artifact], chunks: list[ArtifactChunk]
) -> list[Artifact]:
    """Return artifacts referenced by selected chunks."""
    artifact_ids = {chunk.artifact_id for chunk in chunks}
    return [artifact for artifact in artifacts if artifact.id in artifact_ids]


def _dedupe_chunks(chunks: Iterable[ArtifactChunk]) -> list[ArtifactChunk]:
    """Dedupe chunks while preserving order."""
    seen: set[str] = set()
    result: list[ArtifactChunk] = []
    for chunk in chunks:
        if chunk.id not in seen:
            seen.add(chunk.id)
            result.append(chunk)
    return result


def _compact_artifact(
    artifact: Artifact, prompt_ids: _PromptIdMap
) -> dict[str, str | None]:
    """Return token-light artifact metadata."""
    return {
        "id": prompt_ids.artifact_id(artifact.id),
        "type": artifact.artifact_type_id,
        "title": artifact.title,
    }


def _compact_chunk(
    chunk: ArtifactChunk,
    prompt_ids: _PromptIdMap,
    limits: PerspectiveContextLimits,
) -> dict[str, str | int]:
    """Return token-light source chunk content."""
    return {
        "id": prompt_ids.chunk_id(chunk.id),
        "artifact_id": prompt_ids.artifact_id(chunk.artifact_id),
        "index": chunk.chunk_index,
        "text": chunk.text[: limits.chunk_chars],
    }


def _compact_signal(
    signal: ContextSignal,
    prompt_ids: _PromptIdMap,
    limits: PerspectiveContextLimits,
) -> dict[str, object]:
    """Return token-light signal content."""
    return {
        "id": prompt_ids.signal_id(signal.id),
        "type": signal.signal_type,
        "label": signal.label,
        "value": signal.value,
        "source_links": _compact_source_links(signal.source_links, prompt_ids, limits),
        "metadata": _compact_metadata(signal.metadata),
    }


def _compact_actionable_item(
    item: ActionableItem,
    prompt_ids: _PromptIdMap,
    limits: PerspectiveContextLimits,
) -> dict[str, object]:
    """Return token-light actionable item content."""
    return {
        "id": prompt_ids.item_id(item.id),
        "type": item.item_type,
        "title": item.title,
        "description": item.description,
        "readiness": item.readiness_status.value,
        "source_links": _compact_source_links(item.source_links, prompt_ids, limits),
    }


def _compact_view(
    view: PerspectiveView,
    prompt_ids: _PromptIdMap,
    limits: PerspectiveContextLimits,
) -> dict[str, object]:
    """Return token-light deterministic view content."""
    return {
        "id": view.view_definition_id,
        "title": view.title,
        "sections": [
            {
                "id": section.id,
                "title": section.title,
                "content": section.content,
                "evidence_links": [
                    {
                        "source": _compact_source_link(
                            evidence.source, prompt_ids, limits
                        ),
                        "confidence": evidence.confidence,
                        "note": evidence.note,
                    }
                    for evidence in section.evidence_links
                ],
            }
            for section in view.sections
        ],
    }


def _compact_source_links(
    links: list[SourceLink],
    prompt_ids: _PromptIdMap,
    limits: PerspectiveContextLimits,
) -> list[dict[str, object]]:
    """Return compact source references."""
    return [
        _compact_source_link(link, prompt_ids, limits)
        for link in links
        if link.chunk_id or link.artifact_id
    ]


def _compact_source_link(
    link: SourceLink,
    prompt_ids: _PromptIdMap,
    limits: PerspectiveContextLimits,
) -> dict[str, object]:
    """Return one compact source reference."""
    return {
        "artifact_id": prompt_ids.artifact_id(link.artifact_id),
        "chunk_id": prompt_ids.chunk_id(link.chunk_id) if link.chunk_id else None,
        "label": link.label,
        "excerpt": (link.excerpt or "")[: limits.source_excerpt_chars],
    }


def _compact_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Keep only metadata useful to synthesis."""
    keys = {
        "generated_by",
        "explicit_or_inferred",
        "confidence",
        "rationale",
        "summary",
        "reason",
    }
    return {key: value for key, value in metadata.items() if key in keys}


def _normalize_entity_name(value: str) -> str:
    """Normalize entity names for LLM relationship resolution."""
    return " ".join(value.lower().split())
