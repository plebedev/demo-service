# demo-text-tools

`demo-text-tools` is an internal Rust sidecar service for deterministic text operations used by the demo backend. It is intentionally small: no database, no LLM calls, no public ingress, and no browser-facing surface.

## Endpoints

```text
GET  /health
POST /v1/text/normalize
POST /v1/text/chunk
POST /v1/text/analyze
POST /v1/input/inspect
```

## Run Locally

Start Rust first:

```bash
cd /Users/plebedev/github/demo/demo-service
task text-tools:run
```

Then start the Python backend in another terminal:

```bash
cd /Users/plebedev/github/demo/demo-service
TEXT_TOOLS_ENABLED=true TEXT_TOOLS_BASE_URL=http://127.0.0.1:8081 task dev
```

The backend keeps `TEXT_TOOLS_ENABLED=false` by default until integration is explicitly enabled.

## IntelliJ

Create a Cargo run configuration:

```text
Name: demo-text-tools
Command: run
Working directory: /Users/plebedev/github/demo/demo-service/text-tools
Environment:
  TEXT_TOOLS_HOST=127.0.0.1
  TEXT_TOOLS_PORT=8081
  RUST_LOG=info
```

Create a backend run configuration separately and start it after the Rust service:

```text
Working directory: /Users/plebedev/github/demo/demo-service
Command: poetry run uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000
Environment:
  TEXT_TOOLS_ENABLED=true
  TEXT_TOOLS_BASE_URL=http://127.0.0.1:8081
```

## Sample Requests

```bash
curl -s http://127.0.0.1:8081/health
```

```bash
curl -s http://127.0.0.1:8081/v1/text/normalize \
  -H 'Content-Type: application/json' \
  -d '{"text":"  hello   world\n\nagain "}'
```

```bash
curl -s http://127.0.0.1:8081/v1/text/chunk \
  -H 'Content-Type: application/json' \
  -d '{"text":"long text goes here","chunk_size":100,"chunk_overlap":10}'
```

```bash
curl -s http://127.0.0.1:8081/v1/text/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text":"hello https://example.test person@example.test","limits":{"max_bytes":1000,"max_chunk_size":100,"chunk_overlap":10}}'
```

```bash
curl -s http://127.0.0.1:8081/v1/input/inspect \
  -H 'Content-Type: application/json' \
  -d '{"file_name":"notes.txt","content_type":"text/plain","size_bytes":1234}'
```
