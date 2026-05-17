# Job Search Domain Pack

`app/domains/job_search/` is the first real Context Engine domain pack. It is a
reference implementation for career-context extraction, not a standalone app and
not shared core infrastructure.

`domain.yaml` is the domain manifest loaded by `register.py` for artifact type,
view, unsupported-input, and extractor-routing metadata.

## Registered Inputs

- `job_description`
- `resume`
- `recruiter_message`
- `interview_notes`
- `company_research`
- `personal_story`
- `compensation_notes`
- `follow_up_notes`

The MVP registers all eight artifact types so they can be ingested and
source-linked. Four artifact types currently have deterministic extractors:
`job_description`, `resume`, `interview_notes`, and `personal_story`.
`recruiter_message`, `company_research`, `compensation_notes`, and
`follow_up_notes` are intentionally metadata/task-ready only in this milestone.

## Registered Extensions

- Extractors: job description, resume, interview notes, personal story
- Perspectives: role fit, interview prep, resume positioning, application
  pipeline, compensation and scope risk
- Task generator: job-search next actions mapped to generic `ActionableItem`

All outputs use generic Context Engine primitives and preserve `SourceLink`
provenance.
