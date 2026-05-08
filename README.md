# Invite-Only Demo Backend API

This repository is the phase-1 backend API for the invite-only demo. It mirrors the frontend repo's no-registry deploy approach: build locally, ship the image and committed source to the VM, import into `k3s`, and deploy with Helm.

The browser-facing demo is deployed at [demo.lebedev.ai](https://demo.lebedev.ai);
this backend is reached through the frontend/BFF and cluster-internal service
routing.

## What is included

- FastAPI app with:
  - `/health`
  - `/ready`
  - `/api/status` protected by a signed phase-1 access token
  - `/api/access/redeem` for invitation-code validation and token issuance
  - `/api/access/invite-requests` for public invite request intake
  - `/api/access/verify` for stored-token validation
  - `/api/runs/*` protected endpoints for draft creation, listing, editing, and submission
  - `/api/internal/admin/invitations/*` for internal invite management
  - placeholder webhook endpoints for Twilio and Plivo
- SQLAlchemy 2.x models and sessions
- Pydantic 2 settings and response models
- Alembic config and an initial migration
- invitation code and redemption tracking tables
- persisted `runs` table for the M2 demo shell
- normalized ingestion storage for M3: raw pasted text, accepted file extracts,
  and summary/warning metadata
- YAML-backed workflow config loading, including per-agent model/provider,
  tool access, bounded handoffs, parallel metadata, and post-processor references
- bounded M5 runtime execution for `messy-notes-v1`, with structured
  `run_events`, final brief storage, and post-processor audit results
- pytest coverage for invite validation, token validation, and protected route access control
  plus demo-run creation, retrieval, editing, submission, and deterministic ingestion coverage
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

The backend now supports two configuration modes:

- Local development: auto-load `local/.env.backend`
- Deployed environments: use real environment variables only

When `ENVIRONMENT=local` or `ENVIRONMENT` is unset, the app loads
`local/.env.backend` automatically. When `ENVIRONMENT` is anything else such as
`demo` or `production`, the dotenv file is ignored and only process
environment variables are used.

You can override the local dotenv path for one-off runs with `LOCAL_ENV_FILE`.

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
| `ACCESS_TOKEN_SIGNING_KEY` | HMAC signing key for invite-issued access tokens |
| `ACCESS_TOKEN_TTL_SECONDS` | Lifetime for the signed phase-1 access token |
| `ADMIN_API_SECRET` | Shared secret for internal invitation-management endpoints |
| `DEFAULT_WORKFLOW_KEY` | Workflow key assigned to newly created runs |
| `WORKFLOW_CONFIG_DIR` | Directory containing workflow YAML definitions |
| `POST_PROCESSOR_CONFIG_PATH` | YAML file defining workflow post-processors |
| `MAX_FILES_PER_RUN` | Phase-1 limit for files per run |
| `MAX_FILE_SIZE_BYTES` | Phase-1 limit for file upload size |
| `MAX_EXTRACTED_TEXT_BYTES` | Total extracted-text budget kept from accepted files |
| `MAX_PASTED_TEXT_BYTES` | Maximum raw pasted text persisted on the run |
| `MAX_TOTAL_WORKFLOW_TEXT_BYTES` | Maximum normalized text passed to workflow execution |
| `RAG_EMBEDDING_PROVIDER` | Embedding provider for local RAG ingestion/search, currently `ollama` |
| `RAG_OLLAMA_BASE_URL` | Local Ollama base URL, default `http://127.0.0.1:11434` |
| `RAG_EMBEDDING_MODEL` | Ollama embedding model, default `all-minilm:l12-v2` |
| `RAG_ORACLE_EMBEDDING_MODEL` | Oracle ONNX model object used with `VECTOR_EMBEDDING`, default `MINILM_L12_V2` |
| `RAG_CHUNK_SIZE` | Character chunk target for RAG documents, default `800` |
| `RAG_CHUNK_OVERLAP` | Character overlap between RAG chunks, default `80` |
| `EMAIL_PROVIDER` | Existing draft provider selector for internal draft endpoints |
| `INVITE_EMAIL_FROM` | Legacy draft sender placeholder |
| `INVITE_EMAIL_REPLY_TO` | Legacy draft reply-to placeholder |
| `INVITE_EMAIL_BASE_URL` | Public frontend URL used in invite email copy |
| `INVITE_EMAIL_DRAFT_PROVIDER` | PydanticAI provider for personalized invite email drafting, default `openai` |
| `INVITE_EMAIL_DRAFT_MODEL` | Small model used for invite email drafting, default `gpt-5-mini` |
| `INVITE_EMAIL_BCC_ADDRESS` | Operator address BCC'd on every automatic invite email |
| `OCI_EMAIL_SMTP_HOST` | OCI Email Delivery SMTP host |
| `OCI_EMAIL_SMTP_PORT` | OCI Email Delivery SMTP port, usually `587` |
| `OCI_EMAIL_SMTP_USERNAME` | OCI Email Delivery SMTP username |
| `OCI_EMAIL_SMTP_PASSWORD` | OCI Email Delivery SMTP password |
| `OCI_EMAIL_FROM_ADDRESS` | Verified sender address for OCI Email Delivery |
| `OCI_EMAIL_FROM_NAME` | Display name for automatic invite emails |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID for SMS delivery |
| `TWILIO_AUTH_TOKEN` | Twilio auth token for SMS delivery and webhook signature checks |
| `TWILIO_FROM_NUMBER` | Twilio sender phone number used for completion texts |
| `SMS_NOTIFICATION_ENABLED` | Feature flag returned as `features.SmsNotification`; defaults to `false` until SMS campaign approval |
| `SMS_REPLY_PROVIDER` | PydanticAI provider for SMS reply/opt-out classification, default `openai` |
| `SMS_REPLY_MODEL` | Small model used for bounded SMS replies, default `gpt-5-mini` |
| `OPENAI_API_KEY` | API key for workflow agents using OpenAI models |
| `ANTHROPIC_API_KEY` | API key for workflow agents or post-processors using Anthropic models |
| `FIREWORKS_API_KEY` | Reserved future provider key for FireworksAI |
| `OPENROUTER_API_KEY` | Reserved future provider key for OpenRouter |

The app accepts either:

- `DATABASE_URL`
- or the Oracle split configuration `DB_DSN` + `DB_USER` + `DB_PASSWORD`

For Oracle Cloud deployments, prefer OCI Vault / Secret Management as the real secret source, then sync those values into Kubernetes Secrets or environment variables at deploy time.

## Demo guardrails

This is a demo, not a general-purpose assistant.

Supported phase-1 inputs:

- pasted text
- text file upload
- PDF upload with extractable text

Not supported in phase 1:

- images
- OCR
- audio/video
- web lookup

Follow-up constraints:

- one generated brief per run
- exactly one brief-scoped follow-up question per completed run
- second follow-ups are rejected
- unrelated broad chat is rejected
- follow-up response state is stored with the run
- SMS replies are limited to two LLM-generated turns per notification thread

The backend publishes these guardrails through the protected status and
access-verification responses. Submitted runs execute the bounded messy-notes
workflow, persist a generated brief, store structured run events, and run the
tool/handoff audit post-processor.

`GET /api/status` also returns feature availability under `features`. The first
flag is `SmsNotification`, controlled by `SMS_NOTIFICATION_ENABLED`. This flag
can stay `false` while the backend remains healthy and available.

## Invite request intake

Visitors without an invitation code can submit a simple invite request through:

```text
POST /api/access/invite-requests
```

The endpoint stores name, normalized email, short reason, request status, user
agent, and an IP hash, then queues background fulfillment. The background task
creates a linked invitation code with `max_uses = 10`, drafts a short
personalized invite email from the request context with PydanticAI, falls back
to a deterministic template if drafting fails, and sends through OCI Email
Delivery SMTP. `INVITE_EMAIL_BCC_ADDRESS` is included as BCC on every automatic
invite email.

Invite fulfillment records `fulfillment_status`, `fulfilled_at`,
`email_sent_at`, and `fulfillment_error` on the invite request. If sending
fails, the request and generated code remain persisted and the failure is
logged for later retry.

## M6 demo polish APIs

M6 adds protected API support for first-run usability and bounded follow-up:

- `GET /api/runs/samples` returns curated messy-note sample sets
- `GET /api/runs/<run_id>/summary` returns a compact execution summary for demos
- `POST /api/runs/<run_id>/sample` loads one sample set into a draft run
- `POST /api/runs/<run_id>/follow-up` answers exactly one brief-scoped follow-up
- `POST /api/runs/sms-status` checks US phone validity and permanent opt-out status
- `POST /api/runs/<run_id>/notification-preference` stores optional SMS preference and a normalized US phone number

Notification sending is intentionally not an LLM tool. The service persists the
preference on the run and sends Twilio SMS from coded backend completion logic.
Inbound Twilio replies are accepted at:

```text
POST /api/webhooks/twilio/sms
```

Configure that public URL in Twilio as the messaging webhook. The demo Helm
values expose only `/api/webhooks/twilio/sms` for backend ingress; internal admin
APIs remain unexposed. Webhook signature validation is performed when Twilio
sends `X-Twilio-Signature` and `TWILIO_AUTH_TOKEN` is configured.

SMS reply behavior is intentionally bounded:

- obvious STOP-like messages are handled deterministically
- close opt-out variants are classified by the configured small PydanticAI model
- opted-out phone numbers are stored in `sms_opt_outs` and blocked permanently
- future completion sends to blocked numbers are skipped and recorded
- the first two non-opt-out inbound replies get concise LLM-generated responses
- third and later replies receive a canned limit message pointing back to the app

Run tests are part of the normal workflow:

```bash
task test
task lint
task build
```

## Messy Notes run namespace

Messy Notes runs are scoped by the invitation code embedded in the signed access
token. New `/api/runs/*` rows store `runs.invitation_code_id`; protected run
lookups return rows for the caller's invite code plus legacy rows where
`invitation_code_id` is still `NULL`.

Legacy `NULL` rows are a compatibility bridge for runs created before
invite-code namespacing. To assign those rows once production ownership is
known, inspect the messy-notes invitation codes and update the legacy rows to
the chosen code id:

```sql
SELECT id, code, label FROM invitation_codes WHERE label = 'messy-notes';
UPDATE runs SET invitation_code_id = <chosen_id> WHERE invitation_code_id IS NULL;
```

A later migration can make `runs.invitation_code_id` non-null after all legacy
rows have been assigned.

## M3 ingestion behavior

The run-ingestion endpoint accepts:

- pasted text
- `.txt` uploads
- PDFs with extractable text

The run-ingestion endpoint rejects:

- images
- OCR-only PDFs
- audio/video
- unsupported binary file types

Trimming is deterministic and intentionally boring:

- keep files in upload order until `MAX_FILES_PER_RUN`
- reject files larger than `MAX_FILE_SIZE_BYTES`
- extract text only from supported file types
- keep the first bytes that fit within `MAX_EXTRACTED_TEXT_BYTES`
- build normalized workflow text as pasted text first, then accepted files in upload order
- trim normalized workflow text by keeping the first bytes that fit within `MAX_TOTAL_WORKFLOW_TEXT_BYTES`

The backend does not imply that it ranked or fully evaluated dropped notes. If something is too large, the stored warnings say so plainly.

## M5 runtime execution

Submitting a run now executes the configured `messy-notes-v1` workflow
synchronously:

- `/api/runs/<run_id>/submit` saves the submitted state and runs the workflow
- `/api/runs/<run_id>/execute` can execute an existing draft/submitted/failed run
- `/api/runs/<run_id>/events` returns structured execution events

The first runtime path is intentionally bounded: orchestrator, extractor,
reconciler, and brief writer hand off only through the configured graph.
Extractor tools run in the one explicit parallel group defined in YAML.

The first post-processor is `audit-tool-usage-and-handoffs`; it reads persisted
run events and stores a structured audit under `post_processor_results_json`.

Run execution tests are included in the normal backend workflow:

```bash
task test
task lint
task build
```

## M4 workflow config

Workflow definitions now live under:

- `app/resources/workflows/*.yaml`
- `app/resources/post_processors/post-processors.yaml`

Startup loads and validates:

- workflow keys and starting agents
- duplicate agent roles
- tool references against the registry
- handoff targets
- parallel-peer metadata
- workflow post-processor references

The initial shipped workflow is `messy-notes-v1`, which configures:

- `orchestrator`
- `extractor`
- `reconciler`
- `brief_writer`

The M5 runtime builds on this config instead of introducing a separate planner.

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

Local development starts Postgres with pgvector plus an Ollama container for
embedding generation. The one-shot `ollama-pull-all-minilm` Compose service
pulls `all-minilm:l12-v2` into the persistent `ollama-data` Docker volume the
first time local infrastructure starts.

Verify pgvector:

```bash
docker exec -it demo-service-postgres psql -U demo_service -d demo_service
```

```sql
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
SELECT '[1,2,3]'::vector;
```

Verify the local embedding model:

```bash
curl http://127.0.0.1:11434/api/embed \
  -d '{"model":"all-minilm:l12-v2","input":"hello world"}'
```

4. Apply migrations:

```bash
task migrate
```

5. Run the API:

```bash
task dev
```

Try:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

Use the internal admin API to mint an invitation code:

```bash
ADMIN_API_SECRET=demo-admin-change-me \
bash deploy/scripts/invitation-admin.sh create demo-local-code local-demo 5
```

Redeem and verify a code locally:

```bash
curl -X POST http://127.0.0.1:8000/api/access/redeem \
  -H 'Content-Type: application/json' \
  -d '{"code":"demo-local-code"}'
```

## Local RAG API smoke test

The protected RAG endpoints let you test document ingestion and scoped vector
search before adding frontend UI. They accept pasted text, `.txt` files, and
PDFs with extractable text. Images, OCR-only PDFs, audio/video, and web lookup
remain outside the demo guardrails.

The backend binds a RAG implementation at the service boundary:

- local Postgres uses app-side chunking, Ollama embeddings, and pgvector search
- Oracle uses native `VECTOR_CHUNKS`, `VECTOR_EMBEDDING`, and vector search

The public API stays the same across environments.

Create an invite code, redeem it, and export the token:

```bash
ADMIN_API_SECRET=demo-admin-change-me \
bash deploy/scripts/invitation-admin.sh create rag-local-code rag-local 5
```

```bash
TOKEN="$(
  curl -s http://127.0.0.1:8000/api/access/redeem \
    -H 'Content-Type: application/json' \
    -d '{"code":"rag-local-code"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
)"
```

Ingest pasted text under one or more labels:

```bash
curl -s http://127.0.0.1:8000/api/rag/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F labels=rag-demo \
  -F labels=messy-notes-v1 \
  -F source=local-note.txt \
  -F title='Local RAG note' \
  -F input_text='Renewal policy: customers with urgent operational risk need concise migration guidance.'
```

Ingest a text or PDF file instead:

```bash
curl -s http://127.0.0.1:8000/api/rag/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F labels=rag-demo \
  -F source=handbook.pdf \
  -F title='Handbook' \
  -F file=@handbook.pdf
```

Search only inside selected labels:

```bash
curl -s http://127.0.0.1:8000/api/rag/search \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"query":"What should I tell a renewal customer?","labels":["rag-demo"],"limit":5}'
```

## Oracle RAG model setup

Oracle production uses native `VECTOR` storage and database-side embedding.
Connect as `ADMIN` only for privileged setup, then load and verify the model as
the application schema that the backend uses, normally `APP_RW`.

As `ADMIN`, grant the app schema the required privileges:

```sql
GRANT CREATE MINING MODEL TO APP_RW;
GRANT EXECUTE ON DBMS_CLOUD TO APP_RW;
GRANT EXECUTE ON DBMS_VECTOR TO APP_RW;
```

Do not use the raw Hugging Face ONNX export for Oracle. It expects transformer
token tensors and can fail with errors such as `ORA-54426`. Use Oracle's
augmented MiniLM model instead:

```bash
mkdir -p ~/Downloads/demo-rag-models
cd ~/Downloads/demo-rag-models

curl -L \
  -o all_MiniLM_L12_v2_augmented.zip \
  'https://adwc4pm.objectstorage.us-ashburn-1.oci.customer-oci.com/p/TtH6hL2y25EypZ0-rrczRZ1aXp7v1ONbRBfCiT-BDBN8WLKQ3lgyW6RxCfIFLdA6/n/adwc4pm/b/OML-ai-models/o/all_MiniLM_L12_v2_augmented.zip'

unzip all_MiniLM_L12_v2_augmented.zip
```

Upload `all_MiniLM_L12_v2.onnx` to a private OCI Object Storage bucket and
create a pre-authenticated request with object-read access. The OCI Console path
is:

```text
Storage -> Buckets -> Create bucket -> Upload object -> Pre-authenticated requests
```

The same can be done with OCI CLI:

```bash
oci os bucket create \
  --name demo-rag-models \
  --compartment-id <compartment_ocid>

oci os object put \
  --bucket-name demo-rag-models \
  --name all_MiniLM_L12_v2.onnx \
  --file ./all_MiniLM_L12_v2.onnx

oci os preauth-request create \
  --bucket-name demo-rag-models \
  --name read-minilm-l12-v2 \
  --access-type ObjectRead \
  --object-name all_MiniLM_L12_v2.onnx \
  --time-expires 2026-05-14T00:00:00Z
```

Connect as `APP_RW` and load the model from the PAR URL. The model name is the
database object name used later in `VECTOR_EMBEDDING`; this app expects
`MINILM_L12_V2`.

```sql
BEGIN
  DBMS_VECTOR.DROP_ONNX_MODEL(
    model_name => 'MINILM_L12_V2',
    force => TRUE
  );
EXCEPTION
  WHEN OTHERS THEN NULL;
END;
/

BEGIN
  DBMS_VECTOR.LOAD_ONNX_MODEL_CLOUD(
    model_name => 'MINILM_L12_V2',
    credential => NULL,
    uri => '<PAR_URL_TO_all_MiniLM_L12_v2.onnx>'
  );
END;
/
```

Verify the model as `APP_RW`:

```sql
SELECT model_name, algorithm, mining_function
FROM user_mining_models
WHERE model_name = 'MINILM_L12_V2';

SELECT VECTOR_DIMENSION_COUNT(
  VECTOR_EMBEDDING(MINILM_L12_V2 USING 'hello world' AS DATA)
) AS dims;
```

Expected dimension count:

```text
384
```

After running Alembic against Oracle, verify the RAG tables as `APP_RW`:

```sql
SELECT table_name
FROM user_tables
WHERE table_name LIKE 'RAG_%'
ORDER BY table_name;

SELECT column_name, data_type
FROM user_tab_columns
WHERE table_name = 'RAG_DOCUMENT_CHUNKS'
ORDER BY column_id;
```

If connected as `ADMIN`, use `ALL_TABLES` to confirm the app-owned objects:

```sql
SELECT owner, table_name
FROM all_tables
WHERE table_name LIKE 'RAG_%'
ORDER BY owner, table_name;
```

Run the load SQL through SQLcl when scripting setup:

```bash
sql APP_RW/'<password>'@'<dsn>' @load_minilm.sql
```

Once the Oracle model and migrations are in place, the same protected RAG API
works against Oracle. Ingestion sends extracted text to Oracle `VECTOR_CHUNKS`,
stores each chunk with `VECTOR_EMBEDDING(MINILM_L12_V2 USING ... AS DATA)`, and
search embeds the query with the same model inside Oracle.

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

Local config files have separate roles:

- `local/.env.backend`
  Backend application settings for local development. The app now reads this
  file automatically in local mode.
- `local/.env.postgres`
  Docker Compose settings for the local Postgres container only.

The local `task dev`, `task migrate`, and `task makemigration` commands no
longer need an explicit `source local/.env.backend` step because the backend
loads that file itself in local mode.

## Tests

Run the normal backend checks with:

```bash
task test
task lint
task build
task verify
```

You can also validate workflow config as part of startup by running:

```bash
poetry run python -c "from app.main import create_app; create_app()"
```

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
task apply-runtime-secret -- \
  DB_PASSWORD 'your-app-rw-password' \
  ACCESS_TOKEN_SIGNING_KEY 'replace-with-random-secret' \
  ADMIN_API_SECRET 'replace-with-internal-admin-secret'
```

The default secret name is `backend-api-secrets` in namespace `demo`.

The demo values file is already wired to look for that existing secret.

You can also update individual keys later without re-sending the others:

```bash
task apply-runtime-secret -- ADMIN_API_SECRET 'rotated-admin-secret'
```

## Registry-free VM deployment

The main deployment flow mirrors the frontend:

```bash
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

- `DEPLOY_PATH`
- `SSH_OPTS`
- `KEEP_REMOTE_RELEASES`
- `RELEASE_NAME`
- `NAMESPACE`
- `VALUES_FILE`

If you are deploying to a fresh cluster, apply the runtime secret first:

```bash
task apply-runtime-secret -- DB_PASSWORD 'your-app-rw-password'
task ship-deploy
```

Default target VM:

```text
ubuntu@openclaw
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

The internal invitation admin API is intended to stay on the cluster-internal service and should not be exposed through ingress.

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

## Internal admin helper

The VM-side invite management helper is [deploy/scripts/invitation-admin.sh](/Users/plebedev/github/demo/demo-service/deploy/scripts/invitation-admin.sh).

Supported commands:

- `create [code] [label] [max_uses]`
- `list`
- `deactivate <invitation_code_id>`
- `stats`
- `requests`
- `request <invite_request_id>`
- `review <invite_request_id> [reviewed|approved|rejected] [note]`
- `issue-draft <invite_request_id> [code] [label] [max_uses] [note]`

It calls the backend internal admin API and never talks directly to the database.
