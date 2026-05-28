# Context Engine Core

The core Context Engine is domain-neutral. It owns generic orchestration,
storage contracts, source links, registries, and optional model execution
contracts. Domain packs own domain-specific extraction, synthesis, and prompts.

LLM-assisted flows use `llm.py`:

- `ContextModelFlowCatalog` loads domain/flow/step model selection.
- `ContextExecutionContext` is passed to domain extensions.
- `PydanticAIContextModelRunner` reuses `app.services.model_factory`.
- Domain wrappers decide how structured model output maps back to generic
  primitives.

Execution modes:

- `deterministic`: run registered deterministic extractors/builders/generators.
- `llm`: prefer structured model output, with deterministic fallback.
- `hybrid`: preserve deterministic output and add/refine model output.

Core source-grounding expectations are generic: derived records need
`SourceLink`/`EvidenceLink` references, and storage rejects durable entities,
relationships, signals, and actionable items without source links. Domain packs
may add stricter validation before output is persisted.

Domain packs may also declare context dependency graphs for their own
perspectives. The core remains neutral: it provides owner-scoped artifacts,
chunks, signals, and actionable items, while the domain decides which of those
records belong in a model-backed synthesis step.
