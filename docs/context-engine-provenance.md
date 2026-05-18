# Provenance Model

Context Engine outputs are source-grounded by default.

`SourceLink` points back to:

- source artifact id
- optional chunk id
- optional character offsets
- optional label
- optional excerpt

Chunks, entities, relationships, signals, actionable items, and perspective
sections can all carry provenance through source links or evidence links.
Durable storage keeps source links both embedded in generic output records and
as `context_source_links` audit rows.

Artifact list/detail APIs expose the original owner-scoped source records back
to the frontend so evidence links can navigate to the underlying artifact. View
sections label evidence as explicit or inferred through section metadata and
evidence notes; the UI should keep that distinction visible.

Rule-based extractors do not emit numeric confidence values. They preserve the
evidence kind instead, because the current pipeline has no calibrated scoring
model.

The MVP does not claim unsupported knowledge. If no source exists for a view
section or task, the UI and API should represent that absence directly.
