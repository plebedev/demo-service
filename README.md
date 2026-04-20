# Backend API Starter

This repository is a production-like FastAPI backend starter for a single-node `k3s` cluster on an Oracle Cloud VM. It mirrors the frontend repo's no-registry deploy approach: build locally, ship the image and committed source to the VM, import into `k3s`, and deploy with Helm.

## What is included

- FastAPI app with:
  - `/health`
  - `/ready`
  - `/api/status`
  - placeholder webhook endpoints for Twilio and Plivo
- SQLAlchemy 2.x models and sessions
- Pydantic 2 settings and response models
- Alembic config and an initial migration
- Production Dockerfile
- `local/` Docker Compose for Postgres-backed local development
- `deploy/` Helm chart and VM ship-deploy scripts
- Poetry for Python dependency management
- `Taskfile.yml` wrappers for common flows

## Repository layout

```text
.
|-- Dockerfile
|-- Taskfile.yml
|-- README.md
|-- alembic/
|-- app/
|-- deploy/
|   |-- helm/
|   |   `-- backend-api/
|   `-- scripts/
`-- local/
    |-- docker-compose.yaml
    `-- scripts/
```

## Stack

- Python 3.14
- FastAPI
- SQLAlchemy 2.x
- Pydantic 2 / `pydantic-settings`
- Alembic
- Postgres for local development
- Oracle Autonomous Database via walletless TLS in deployed environments

## Configuration

The application has a single configuration-loading path: environment variables only.

- Local development: copy local env examples and export them into your shell
- Kubernetes: inject config via ConfigMap and secrets via Helm/Kubernetes Secret

Important variables:

| Variable | Purpose |
|---|---|
| `APP_NAME` | Service name shown in status responses |
| `ENVIRONMENT` | Environment label such as `local` or `demo` |
| `DATABASE_URL` | Full SQLAlchemy connection URL, used for local Postgres by default |
| `DB_DSN` | Oracle Autonomous Database TLS connect descriptor |
| `DB_USER` | Oracle database user, such as `APP_RW` |
| `DB_PASSWORD` | Oracle database password, injected from a Kubernetes Secret |
| `RUN_MIGRATIONS_ON_STARTUP` | If `true`, the container upgrades to the latest Alembic revision before app start |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Future provider credentials |
| `PLIVO_AUTH_ID` / `PLIVO_AUTH_TOKEN` | Future provider credentials |
| `LLM_API_KEY` | Future LLM provider credential |

The app accepts either:

- `DATABASE_URL`
- or the Oracle split configuration `DB_DSN` + `DB_USER` + `DB_PASSWORD`

For Oracle Cloud deployments, prefer OCI Vault / Secret Management as the real secret source, then sync those values into Kubernetes Secrets or environment variables at deploy time.

## Local development

1. Install dependencies:

```bash
poetry install
```

2. Copy env templates:

```bash
cp .env.example .env
cp local/.env.postgres.example local/.env.postgres
cp local/.env.backend.example local/.env.backend
```

3. Start Postgres:

```bash
task local-up
```

4. Export local app settings:

```bash
set -a
source local/.env.backend
set +a
```

5. Apply migrations:

```bash
task migrate
```

6. Run the API:

```bash
task dev
```

Try:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/api/status
```

## Alembic

Apply migrations:

```bash
task migrate
```

Generate a new migration:

```bash
MESSAGE=add-new-table task makemigration
```

The initial scaffold includes one migration that creates the `example_records` table.

The local `task dev`, `task migrate`, and `task makemigration` commands automatically source `local/.env.backend` before running.

## Docker image

The default image tag is the current short git commit SHA. You can override it with `IMAGE_TAG=...` if needed.

Build:

```bash
task docker-build
```

Save image tar:

```bash
task save-image
```

## Oracle demo deployment setup

For the current Oracle Cloud demo shape:

- keep `DB_DSN` and `DB_USER` in [deploy/helm/backend-api/values-demo.yaml](/Users/plebedev/github/demo-service/deploy/helm/backend-api/values-demo.yaml)
- keep `DB_PASSWORD` in a Kubernetes Secret
- use the `APP_RW` user for the backend and migrations

Create or update the runtime secret:

```bash
DB_PASSWORD='your-app-rw-password' task apply-runtime-secret
```

The default secret name is `backend-api-secrets` in namespace `demo`.

The demo values file is already wired to look for that existing secret.

## Registry-free VM deployment

The main deployment flow mirrors the frontend:

```bash
DEPLOY_TARGET=ubuntu@openclaw \
DEPLOY_PATH=/home/ubuntu/backend-api-deploy \
task ship-deploy
```

What it does:

- verifies deploy-relevant files are committed and clean
- uses the current short git SHA as the image tag
- runs local compile checks
- lints the Helm chart
- builds the image locally
- saves and copies the image tar plus committed source bundle to the VM
- imports the image into `k3s` via `sudo k3s ctr images import`
- deploys via Helm using the imported image
- keeps only the newest three remote shipped artifacts/releases by default

Useful variables:

- `DEPLOY_TARGET`
- `DEPLOY_PATH`
- `SSH_OPTS`
- `KEEP_REMOTE_RELEASES`
- `RELEASE_NAME`
- `NAMESPACE`
- `VALUES_FILE`

If you are deploying to a fresh cluster, apply the runtime secret first:

```bash
DB_PASSWORD='your-app-rw-password' task apply-runtime-secret
DEPLOY_TARGET=ubuntu@openclaw \
DEPLOY_PATH=/home/ubuntu/backend-api-deploy \
task ship-deploy
```

## Helm chart

The chart lives under [deploy/helm/backend-api](/Users/plebedev/github/demo-service/deploy/helm/backend-api).

Defaults:

- release name: `backend-api`
- namespace: `demo`
- service type: `ClusterIP`
- ingress: disabled by default
- container port: `8000`
- image pull policy: `IfNotPresent`

Rendered objects:

- `Deployment`
- `Service`
- optional `Ingress`
- `ConfigMap`
- optional chart-managed `Secret`
- optional existing Secret via `existingSecretName`

The chart is intentionally internal-first. Later, if you want selected webhook routes public, you can either:

- enable/create an Ingress for this service with narrow webhook paths, or
- split webhook exposure into a separate ingress or gateway rule while leaving most backend API routes internal behind the frontend/BFF

## Rollback

Show history:

```bash
task history
```

Rollback:

```bash
REVISION=1 task rollback
```

## Oracle vs local DB notes

- Local development is configured for Postgres through Docker Compose.
- Deployed environments should use the Oracle split envs:
  - `DB_DSN`
  - `DB_USER`
  - `DB_PASSWORD`
- The recommended service for the backend API is the `..._tp` service, not `..._high`.
- The backend currently expects the read/write user in production, such as `APP_RW`.
- The starter schema uses generic SQLAlchemy types to avoid obvious cross-dialect issues, but you should still test future migrations against Oracle before relying on local Postgres behavior alone.
