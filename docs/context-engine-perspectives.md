# Perspective System

Perspective builders materialize source-grounded `PerspectiveView` objects from
owner-scoped generic context. The API endpoint is:

```text
GET /api/context/domains/{domain_id}/views/{view_definition_id}
```

Each response contains:

- `PerspectiveView`
- `ViewSection`
- `EvidenceLink`
- `SourceLink`

The first workbench milestone materializes five Job Search perspectives: Role
Fit, Interview Prep, Resume Positioning, Application Pipeline, and Compensation
and Scope Risk. Sections include evidence links and metadata that lets the UI
distinguish explicit source signals from inferred risk/judgment signals.

The builder receives `PerspectiveBuildContext`, which contains artifacts,
chunks, entities, relationships, signals, and actionable items for the signed
invitation-code owner. This keeps views reusable across future domains without
hardcoding domain-specific dashboard models in shared core.
