#!/usr/bin/env bash
set -euo pipefail

BACKEND_ADMIN_BASE_URL="${BACKEND_ADMIN_BASE_URL:-http://127.0.0.1:8000/api/internal/admin/invitations}"
ADMIN_API_SECRET="${ADMIN_API_SECRET:-}"

if [[ -z "${ADMIN_API_SECRET}" ]]; then
  echo "ADMIN_API_SECRET is required."
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage:"
  echo "  $0 create [code] [label] [max_uses]"
  echo "  $0 list"
  echo "  $0 deactivate <invitation_code_id>"
  echo "  $0 stats"
  exit 1
fi

command_name="$1"
shift

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"

  if [[ -n "${body}" ]]; then
    curl --silent --show-error --fail \
      -X "${method}" \
      -H "Content-Type: application/json" \
      -H "X-Admin-Secret: ${ADMIN_API_SECRET}" \
      -d "${body}" \
      "${BACKEND_ADMIN_BASE_URL}${path}" | python3 -m json.tool
    return
  fi

  curl --silent --show-error --fail \
    -X "${method}" \
    -H "X-Admin-Secret: ${ADMIN_API_SECRET}" \
    "${BACKEND_ADMIN_BASE_URL}${path}" | python3 -m json.tool
}

case "${command_name}" in
  create)
    code="${1:-}"
    label="${2:-}"
    max_uses="${3:-}"
    payload="{"
    separator=""
    if [[ -n "${code}" ]]; then
      payload="${payload}\"code\":\"${code}\""
      separator=","
    fi
    if [[ -n "${label}" ]]; then
      payload="${payload}${separator}\"label\":\"${label}\""
      separator=","
    fi
    if [[ -n "${max_uses}" ]]; then
      payload="${payload}${separator}\"max_uses\":${max_uses}"
    fi
    payload="${payload}}"
    request POST "" "${payload}"
    ;;
  list)
    request GET ""
    ;;
  deactivate)
    if [[ $# -lt 1 ]]; then
      echo "deactivate requires an invitation_code_id"
      exit 1
    fi
    request POST "/$1/deactivate"
    ;;
  stats)
    request GET "/stats"
    ;;
  *)
    echo "Unknown command: ${command_name}"
    exit 1
    ;;
esac
