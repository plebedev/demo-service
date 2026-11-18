# Context Engine Extraction Pipeline

The generic ingestion flow is owned by `app/core/context_engine/service.py`.

```text
IngestionRequest[] (one domain, one owner)
  -> validate registered domain, owner scope, artifact types, and text
  -> replay stored results when the idempotency key was already recorded
  -> for each request, in order:
       build Artifact
       chunk text into ArtifactChunk records
       run domain-registered Extractor implementations
       run domain-registered TaskGenerator implementations
       validate chunk and SourceLink provenance
  -> ContextRepository.store_ingestion_batch(IngestionBatch)
       persist Artifact, ArtifactChunk, ContextEntity, ContextRelationship,
       ContextSignal, ActionableItem, SourceLink audit rows, and the
       idempotency record in one transaction with a single commit
```

`ContextEngineService.ingest_artifacts` is the only ingestion path.
`ingest_artifact` and `ingest_payload` delegate to it as single-item batches.
Extensions run before anything is persisted, so they receive an `Artifact` that
is not yet stored and must not depend on repository state for it. If any
extension raises, provenance validation fails, or persistence fails, the whole
batch is discarded. Per-artifact failures raise `ArtifactIngestionError`, a
`ValueError` subclass carrying the failing request index.

Domain packs decide what to extract. Core only orchestrates generic extension
contracts and persistence.

The API accepts JSON text ingestion, atomic JSON batch ingestion (1 to 20
artifacts), and multipart upload ingestion. Uploads are normalized into the
same `IngestionRequest` path after UTF-8 text extraction or PDF embedded-text
extraction, so persistence, provenance, extraction, idempotency, and owner
scoping remain identical.

Idempotent requests pass an `IngestionIdempotency` (key plus request
fingerprint). Repositories store the serialized results with the key, scoped to
domain and owner. A repeat with the same fingerprint returns the stored results
without running extensions, a different fingerprint raises
`IdempotencyConflictError`, and a concurrent insert of the same key makes the
repository raise `IdempotencyKeyExistsError`; the service then replays the
winning batch.

The current Job Search MVP uses deterministic extractors so tests remain stable
and costs stay at zero. A later bounded model step can be added behind the same
extension interfaces without creating job-search-specific core code.

Extractor outputs keep extractor registration order, and task generator output
is appended in task generator registration order.

Extractors may expose `artifact_type_ids` as an optional dispatch hint. When
present, the service runs that extractor only for matching registered artifact
types; otherwise the extractor remains self-contained and can decide whether to
return output.

Current `job_search` extraction covers all registered artifact types. Canonical
artifacts have specialized extractors, while recruiter messages, company
research, compensation notes, and follow-up notes use a supplemental note
extractor for source-grounded signals and actionable-item generation.
