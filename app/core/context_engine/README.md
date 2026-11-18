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

Ingestion is atomic. `ContextEngineService.ingest_artifacts` runs extensions for
every request in memory, then hands one `IngestionBatch` to
`ContextRepository.store_ingestion_batch`, which persists everything with a
single commit or nothing at all. Single-artifact ingestion is a batch of one.
Optional `IngestionIdempotency` input makes repeats return stored results; keys
are scoped to domain and owner (`idempotency.py`, `errors.py`).

Core source-grounding expectations are generic: derived records need
`SourceLink`/`EvidenceLink` references, and `validation.py` rejects chunks and
derived records whose links point at another artifact, at a chunk the
producing artifact does not own, or at offsets outside the referenced text.
Both repository implementations apply the same validation. Domain packs may add
stricter validation before output is persisted.

Domain packs may also declare context dependency graphs for their own
perspectives. The core remains neutral: it provides owner-scoped artifacts,
chunks, signals, and actionable items, while the domain decides which of those
records belong in a model-backed synthesis step.
