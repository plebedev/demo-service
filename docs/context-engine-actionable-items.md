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
GET /api/context/domains/{domain_id}/tasks
```

Actionable items are recommendations only in this milestone. No autonomous
execution agents are invoked.
