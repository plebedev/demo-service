#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${LOCAL_DIR}/.." && pwd)"
POSTGRES_ENV_FILE="${LOCAL_DIR}/.env.postgres"

if [[ ! -f "${POSTGRES_ENV_FILE}" ]]; then
  echo "Missing ${POSTGRES_ENV_FILE}. Copy local/.env.postgres.example first."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${POSTGRES_ENV_FILE}"
set +a

TEST_POSTGRES_DB="${TEST_POSTGRES_DB:-${POSTGRES_DB}_test}"
export POSTGRES_PORT="${TEST_POSTGRES_PORT:-55432}"
if [[ ! "${TEST_POSTGRES_DB}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "TEST_POSTGRES_DB must be a simple PostgreSQL database identifier."
  exit 1
fi
case "${TEST_POSTGRES_DB}" in
  *[Tt][Ee][Ss][Tt]*) ;;
  *)
    echo "TEST_POSTGRES_DB must contain 'test' because tests truncate tables."
    exit 1
    ;;
esac

compose=(
  docker compose
  -f "${LOCAL_DIR}/docker-compose.yaml"
  --env-file "${POSTGRES_ENV_FILE}"
)

"${compose[@]}" up -d postgres

for _ in {1..30}; do
  if "${compose[@]}" exec -T postgres \
    pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! "${compose[@]}" exec -T postgres \
  pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
  echo "Local PostgreSQL did not become ready."
  exit 1
fi

database_exists="$(
  "${compose[@]}" exec -T postgres \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '${TEST_POSTGRES_DB}'"
)"
if [[ "${database_exists}" != "1" ]]; then
  "${compose[@]}" exec -T postgres \
    createdb -U "${POSTGRES_USER}" "${TEST_POSTGRES_DB}"
fi

if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  export TEST_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${TEST_POSTGRES_DB}"
fi

cd "${REPO_DIR}"
poetry run python -m pytest "$@"
