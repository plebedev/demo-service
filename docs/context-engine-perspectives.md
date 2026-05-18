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

The current frontend renders those generic objects with a decision-support
hierarchy:

1. synthesized section conclusion
2. why the conclusion matters
3. top grouped supporting evidence
4. expandable detailed evidence
5. additional explicit or inferred signals

This is a rendering convention, not a new core model. Shared Context Engine code
still only returns `PerspectiveView`, `ViewSection`, `EvidenceLink`, and
metadata. Domain packs can influence synthesis quality through section titles,
content ordering, evidence notes, `signal_types`, and `evidence_kinds`, while
the UI remains responsible for visual hierarchy and evidence grouping.

Perspective intent should remain distinct:

- Role Fit: "How strong is my fit?"
- Interview Prep: "What should I prepare for?"
- Resume Positioning: "How should I position myself?"
- Application Pipeline: "What should I do next?"
- Compensation and Scope Risk: "Is this opportunity structurally attractive?"

The builder receives `PerspectiveBuildContext`, which contains artifacts,
chunks, entities, relationships, signals, and actionable items for the signed
invitation-code owner. This keeps views reusable across future domains without
hardcoding domain-specific dashboard models in shared core.
