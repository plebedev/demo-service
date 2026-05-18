# Actionable-Item Flow

Domain task generators produce generic `ActionableItem` objects. The shared core
does not know about resumes, recruiters, interviews, or compensation; it only
stores item type, title, description, readiness status, metadata, and source
links.

Readiness statuses used by the Job Search domain pack include:

- `ready_for_agent`
- `needs_human_clarification`
- `needs_source_material`
- `needs_decision`
- `blocked`
- `needs_review`

The protected owner-scoped API endpoint is:

```text
GET /api/context/domains/{domain_id}/actionable-items
GET /api/context/domains/{domain_id}/tasks  # deprecated compatibility alias
```

The workbench renders readiness as an operational triage signal:
`ready_for_agent` items may be suitable for future delegated drafting after
human review, while human clarification, decision, source-material, review, and
blocked items remain explicitly human-owned. Every item must preserve the source
links that explain why it was generated.

The frontend groups items by readiness before rendering individual cards. Each
card should answer:

- what work is being recommended
- why the item exists
- which evidence supports it
- whether it is human-owned or potentially agent-suitable after review

This grouping is intentionally UI-level. The backend continues to expose generic
`ActionableItem` records, not experience-specific lanes or execution queues.

Actionable items are recommendations only in this milestone. No autonomous
execution agents are invoked.
