# Job Search Domain Pack

`app/domains/job_search/` is the first real Context Engine domain pack. It is a
reference implementation for career-context extraction, not a standalone app and
not shared core infrastructure.

## Registered Inputs

- `job_description`
- `resume`
- `recruiter_message`
- `interview_notes`
- `company_research`
- `personal_story`
- `compensation_notes`
- `follow_up_notes`

## Registered Extensions

- Extractors: job description, resume, interview notes, personal story
- Perspectives: role fit, interview prep, resume positioning, application
  pipeline, compensation and scope risk
- Task generator: job-search next actions mapped to generic `ActionableItem`

All outputs use generic Context Engine primitives and preserve `SourceLink`
provenance.
