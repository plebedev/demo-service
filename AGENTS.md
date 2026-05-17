# Agent Notes

## Purpose

This repo is the backend API only. It is a FastAPI service with SQLAlchemy, Alembic, and Oracle support for deployed environments.

It is also the backend home for shared Context Engine infrastructure, domain-pack registration, backend experience registration, workflow execution, artifact ingestion, persistence, provenance, extraction orchestration, context graph primitives, generic signals, model registry, telemetry, and future MCP exposure.

This repo is not a standalone job-search service. Job Search / Career Context is the first reference domain pack, and job-search logic must stay out of shared core modules.

## Platform structure

Use these locations for Context Engine work:

- shared domain-neutral core: `app/core/context_engine/`
- domain packs: `app/domains/`
- first reference domain pack: `app/domains/job_search/`
- backend experience registration/composition: `app/experiences/`

Forbidden shared-core locations:

- `app/core/job_search/`
- `app/core/interviews/`
- `app/core/resumes/`
- `app/core/job_requirements.py`
- `app/core/interview_questions.py`

Shared core should use generic names such as `Artifact`, `ArtifactType`, `ArtifactChunk`, `EmbeddingRecord`, `SourceLink`, `EvidenceLink`, `ContextSignal`, `ContextEntity`, `ContextRelationship`, `Perspective`, `PerspectiveView`, `ViewSection`, `ActionableItem`, `ReadinessStatus`, `DomainPack`, `DomainRegistry`, `Extractor`, `PerspectiveBuilder`, `TaskGenerator`, `ViewDefinition`, `Experience`, `ExperienceRegistry`, and `WorkflowDefinition`.

Domain-specific names may exist under `app/domains/job_search/`.

## Context Engine rules

- Keep `app/core/context_engine/` domain-neutral.
- Keep domain-specific logic behind registered domain-pack implementations.
- Keep experience-specific logic behind registered experiences.
- The core should be able to load zero, one, or many domain packs.
- The core should be able to load zero, one, or many experiences.
- A domain pack should be replaceable without changing core code.
- An experience should be replaceable without changing core code.
- Add unit tests for interface and registry behavior.
- Use clear Pydantic models for contracts.
- If database integration is not already present for a feature, implement repository interfaces and an in-memory adapter first.
- Do not introduce a graph database or separate vector DB for MVP.
- Do not tightly couple domain packs to future MCP exposure.

## Normal workflow

### Local

```bash
task install
task local-up
task migrate
task dev
```

- local backend port: `8000`
- local database: Postgres via `local/docker-compose.yaml`
- local tasks source `local/.env.backend`

### Deploy

```bash
DB_PASSWORD='...' task apply-runtime-secret
task ship-deploy
```

Defaults:

- deploy target: `ubuntu@openclaw`
- remote path: `/home/ubuntu/backend-api-deploy`
- namespace: `demo`
- release name: `backend-api`
- runtime secret name: `backend-api-secrets`

## Database model

### Local

- backend uses `DATABASE_URL`
- expected local DB is Postgres
- local Postgres exists only for development speed and convenience

### Deployed

- backend uses Oracle split envs:
  - `DB_DSN`
  - `DB_USER`
  - `DB_PASSWORD`
- current deployed DB user is `APP_RW`
- Oracle service should be the `..._tp` service for the API workload
- production database compatibility means Oracle compatibility

## Migration rules

- Alembic is the migration system
- Migrations currently run automatically on container startup when `RUN_MIGRATIONS_ON_STARTUP=true`
- Local migration commands:
  - `task migrate`
  - `MESSAGE=... task makemigration`
- Postgres is not the source of truth for migration behavior
- Every migration must be written to run correctly against Oracle in deployed environments
- A migration that works only on local Postgres is considered incorrect
- Future migration changes must be checked for Oracle compatibility, not only Postgres compatibility
- Avoid raw SQL that assumes Postgres semantics when SQLAlchemy can express it portably
- If raw SQL is necessary, write it with Oracle behavior in mind first and then verify the local Postgres path separately

## Deployment model

- No image registry is used in the normal flow
- Image builds happen locally
- Images are shipped to the VM as tar archives
- Remote deploy imports images into `k3s` and runs Helm
- Image tags default to short git SHA
- Runtime secrets are provided through Kubernetes Secrets

## Secrets model

- Pods consume Kubernetes Secrets
- OCI Vault / Secret Manager is planned as upstream source of truth later
- Current working flow syncs secret values into k8s Secret before deploy

## Important files

- `Taskfile.yml`
- `app/core/config.py`
- `app/db/session.py`
- `app/api/routes/system.py`
- `alembic/env.py`
- `deploy/helm/backend-api/`
- `deploy/scripts/apply-runtime-secret.sh`
- `deploy/scripts/ship-deploy.sh`
- `deploy/scripts/remote-deploy.sh`

## Current decisions

- single-node `k3s` on Oracle VM
- Traefik exists but backend is internal-first
- frontend reaches backend through BFF and cluster DNS
- local DB is Postgres for speed and convenience
- deployed DB is Oracle Autonomous Database
- when local and production database behavior differ, optimize for production Oracle correctness

## When making changes

- If you change env conventions, update `README.md`, `.env.example`, `local/.env.backend.example`, and Helm values together
- If you change SQL used in readiness/status or migrations, consider Oracle syntax differences first
- If you change API responses used by the frontend, update `demo-web-app` in the same session when possible
- Do not mark migration work complete until the Oracle production path has been considered explicitly
- If you add Context Engine core behavior, explicitly confirm that no job-search logic leaked into core
- If you add backend experience behavior, explicitly confirm that it reuses shared auth, orchestration, storage, ingestion, and registry infrastructure
