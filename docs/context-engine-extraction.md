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

The current Job Search MVP uses deterministic extractors so tests remain stable
and costs stay at zero. A later bounded model step can be added behind the same
extension interfaces without creating job-search-specific core code.

Extractors may expose `artifact_type_ids` as an optional dispatch hint. When
present, the service runs that extractor only for matching registered artifact
types; otherwise the extractor remains self-contained and can decide whether to
return output.
