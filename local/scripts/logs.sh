#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

docker compose -f "${LOCAL_DIR}/docker-compose.yaml" --env-file "${LOCAL_DIR}/.env.postgres" logs -f
