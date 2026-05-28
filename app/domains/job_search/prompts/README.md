# Job Search Prompts

This domain pack owns job_search-specific prompts for bounded Context Engine
model steps. The core Context Engine loads model profiles and step routing from
`app/resources/context_engine/model-flows.yaml`, but these templates stay here
because they contain domain interpretation rules.

Templates:

- `artifact_extraction.md`: turns one artifact and its chunks into structured
  generic Context Engine candidates.
- `perspective_synthesis.md`: turns owner-scoped context into a source-grounded
  `PerspectiveView`.
- `actionable_item_synthesis.md`: generates or refines bounded actionable items.

All prompts require source references, confidence labels, explicit-vs-inferred
classification, and rationale. Job requirements must remain role expectations
unless candidate-owned source evidence supports treating them as user strengths.

Perspective prompts receive a bounded context packet selected by the view's
declarative dependency graph in `../domain.yaml`. Persisted ids are compacted
for the model call and remapped back after structured output validation.
The context packet may include source links at chunk or artifact granularity;
model outputs that make new evidence claims still need chunk ids.
