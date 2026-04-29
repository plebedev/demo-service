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
  echo "  $0 requests"
  echo "  $0 request <invite_request_id>"
  echo "  $0 review <invite_request_id> [reviewed|approved|rejected] [note]"
  echo "  $0 issue-draft <invite_request_id> [code] [label] [max_uses] [note]"
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
  requests)
    request GET "/requests"
    ;;
  request)
    if [[ $# -lt 1 ]]; then
      echo "request requires an invite_request_id"
      exit 1
    fi
    request GET "/requests/$1"
    ;;
  review)
    if [[ $# -lt 1 ]]; then
      echo "review requires an invite_request_id"
      exit 1
    fi
    invite_request_id="$1"
    review_status="${2:-reviewed}"
    note="${3:-}"
    payload="{\"status\":\"${review_status}\""
    if [[ -n "${note}" ]]; then
      payload="${payload},\"reviewer_note\":\"${note}\""
    fi
    payload="${payload}}"
    request POST "/requests/${invite_request_id}/review" "${payload}"
    ;;
  issue-draft)
    if [[ $# -lt 1 ]]; then
      echo "issue-draft requires an invite_request_id"
      exit 1
    fi
    invite_request_id="$1"
    code="${2:-}"
    label="${3:-}"
    max_uses="${4:-}"
    note="${5:-}"
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
      separator=","
    fi
    if [[ -n "${note}" ]]; then
      payload="${payload}${separator}\"reviewer_note\":\"${note}\""
    fi
    payload="${payload}}"
    request POST "/requests/${invite_request_id}/issue-code-draft" "${payload}"
    ;;
  *)
    echo "Unknown command: ${command_name}"
    exit 1
    ;;
esac
