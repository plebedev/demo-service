# Context Engine Extraction Pipeline

The generic ingestion flow is owned by `app/core/context_engine/service.py`.

```text
IngestionRequest
  -> validate registered domain and artifact type
  -> persist Artifact
  -> chunk text into ArtifactChunk records
  -> run domain-registered Extractor implementations
  -> run domain-registered TaskGenerator implementations
  -> persist ContextEntity, ContextRelationship, ContextSignal, ActionableItem
  -> persist SourceLink audit rows
```

Domain packs decide what to extract. Core only orchestrates generic extension
contracts and persistence.

The API accepts both JSON text ingestion and multipart upload ingestion. Uploads
are normalized into the same `IngestionRequest` path after UTF-8 text extraction
or PDF embedded-text extraction, so persistence, provenance, extraction, and
owner scoping remain identical.

The current Job Search MVP uses deterministic extractors so tests remain stable
and costs stay at zero. A later bounded model step can be added behind the same
extension interfaces without creating job-search-specific core code.

Extractors may expose `artifact_type_ids` as an optional dispatch hint. When
present, the service runs that extractor only for matching registered artifact
types; otherwise the extractor remains self-contained and can decide whether to
return output.

Current `job_search` extraction covers all registered artifact types. Canonical
artifacts have specialized extractors, while recruiter messages, company
research, compensation notes, and follow-up notes use a supplemental note
extractor for source-grounded signals and actionable-item generation.
