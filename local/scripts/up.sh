#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -f "${LOCAL_DIR}/.env.postgres" ]]; then
  echo "Missing ${LOCAL_DIR}/.env.postgres. Copy local/.env.postgres.example first."
  exit 1
fi

docker compose -f "${LOCAL_DIR}/docker-compose.yaml" --env-file "${LOCAL_DIR}/.env.postgres" up -d
