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

Before anything is persisted, both repositories validate ingestion output with
`app/core/context_engine/validation.py`:

- every chunk belongs to the artifact that produced it, has a unique index, and
  has offsets inside the artifact text; its own source link must point at that
  artifact and, when it names a chunk, at the chunk itself
- every entity, relationship, signal, and actionable item has at least one
  source link, and every link points at the producing artifact
- a link that names a chunk must name one of the producing artifact's chunks,
  and its offsets must fall inside that chunk (or inside the artifact text when
  no chunk is named)
- every artifact in a batch matches the batch domain and owner, and record ids
  are unique within the batch

Durable derived records take their domain and owner from the producing
artifact, so a link cannot attach output to another owner's namespace. A
validation failure rejects the whole ingestion batch.

Artifact list/detail APIs expose the original owner-scoped source records back
to the frontend so evidence links can navigate to the underlying artifact. View
sections label evidence as explicit or inferred through section metadata and
evidence notes; the UI should keep that distinction visible.

Rule-based extractors do not emit numeric confidence values. They preserve the
evidence kind instead, because the current pipeline has no calibrated scoring
model.

The workbench uses provenance as a trust layer, not the primary reading order.
Users see synthesized conclusions first, then grouped top evidence, then an
expandable trail for additional source links. Repeated snippets may be grouped
in the UI, but the underlying `SourceLink` records remain available through the
artifact APIs.

Confidence labels in the UI are deliberately coarse. They communicate evidence
depth and explicit-vs-inferred status as `High confidence`, `Medium confidence`,
or `Low confidence`; they are not numeric model scores.

The MVP does not claim unsupported knowledge. If no source exists for a view
section or task, the UI and API should represent that absence directly.
