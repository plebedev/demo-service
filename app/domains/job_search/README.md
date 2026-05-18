# Job Search Domain Pack

`job_search` is the first reference Context Engine domain pack. Domain-specific
logic stays in this folder; shared core modules remain generic.

The pack now runs in deterministic, LLM, or hybrid mode:

- deterministic extractors/builders/generators provide safe source-grounded
  fallback output.
- LLM-assisted wrappers in `llm.py` call generic Context Engine execution
  contracts and map structured output to `ContextSignal`, `PerspectiveView`, and
  `ActionableItem`.
- prompts live in `prompts/` and require source references, confidence,
  explicit-vs-inferred labels, and rationale.

Important grounding rule: job-description requirements are role expectations.
They are not user strengths unless resume, story, interview-note, or other
candidate-owned evidence supports the match.
