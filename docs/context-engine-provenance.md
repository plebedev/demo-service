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

The MVP does not claim unsupported knowledge. If no source exists for a view
section or task, the UI and API should represent that absence directly.
