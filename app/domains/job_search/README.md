# Job Search Domain Pack

`job_search` is the first reference Context Engine domain pack. Domain-specific
logic stays in this folder; shared core modules remain generic.

The pack now runs in deterministic, LLM, or hybrid mode:

- deterministic extractors/builders/generators provide safe source-grounded
  fallback output.
- LLM-assisted wrappers in `llm.py` call generic Context Engine execution
  contracts and map structured output to `ContextSignal`, `PerspectiveView`, and
  `ActionableItem`.
- Perspective synthesis uses declarative context dependency graphs in
  `domain.yaml`. Each view declares the artifact, signal, actionable-item, and
  chunk dependencies it needs, plus token/item limits.
- Actionable items can enter perspective synthesis through chunk-level or
  artifact-level source links. Task-generator items that point at a whole
  artifact are included when that artifact is represented in the selected
  context packet.
- prompts live in `prompts/` and require source references, confidence,
  explicit-vs-inferred labels, and rationale.

Important grounding rule: job-description requirements are role expectations.
They are not user strengths unless resume, story, interview-note, or other
candidate-owned evidence supports the match.
