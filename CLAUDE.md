# CLAUDE.md

## Purpose

This repo is the backend API only. It is a FastAPI service with SQLAlchemy, Alembic, and Oracle support for deployed environments.

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

## Adding new config values

Every new field added to `app/core/config.py` must be reflected in the Helm chart before the work is considered complete. Omitting this causes `CrashLoopBackOff` on startup because the env var is missing in the pod.

**Non-secret values** (model names, feature flags, URLs, provider names, numeric limits):
- Add to `configEnv` in `deploy/helm/backend-api/values.yaml` with a safe default value
- Example: `VOICE_XAI_MODEL: "grok-voice-think-fast-1.0"`

**Secret values** (API keys, passwords, tokens):
- Do NOT add to `values.yaml` — secrets are injected at deploy time via `task apply-runtime-secret`
- Document the new secret name in `.env.example` and `local/.env.backend.example` only
- The pod reads secrets from the Kubernetes Secret named by `existingSecretName`

**How to tell them apart**: if the value would be unsafe to commit to git, it is a secret. Everything else is a non-secret config value and belongs in `configEnv`.
