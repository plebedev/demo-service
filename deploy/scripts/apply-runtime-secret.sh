#!/usr/bin/env bash
set -euo pipefail

SECRET_NAME="${SECRET_NAME:-backend-api-secrets}"
NAMESPACE="${NAMESPACE:-demo}"

usage() {
  echo "Usage:"
  echo "  $0 SECRET_KEY SECRET_VALUE [SECRET_KEY SECRET_VALUE ...]"
  echo
  echo "Example:"
  echo "  $0 DB_PASSWORD 'demo-password' ADMIN_API_SECRET 'demo-admin-secret'"
}

if [[ $# -eq 0 || $(( $# % 2 )) -ne 0 ]]; then
  usage
  exit 1
fi

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

patch_json="$(
  python3 - "$@" <<'PY'
import json
import sys

args = sys.argv[1:]
string_data = {}

for index in range(0, len(args), 2):
    key = args[index]
    value = args[index + 1]
    string_data[key] = value

print(json.dumps({"stringData": string_data}))
PY
)"

updated_keys=()
literal_args=()

while [[ $# -gt 0 ]]; do
  key="$1"
  value="$2"
  updated_keys+=("${key}")
  literal_args+=(--from-literal="${key}=${value}")
  shift 2
done

if kubectl get secret "${SECRET_NAME}" --namespace "${NAMESPACE}" >/dev/null 2>&1; then
  kubectl patch secret "${SECRET_NAME}" \
    --namespace "${NAMESPACE}" \
    --type merge \
    --patch "${patch_json}" >/dev/null
else
  kubectl create secret generic "${SECRET_NAME}" \
    --namespace "${NAMESPACE}" \
    "${literal_args[@]}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
fi

echo "Updated secret ${SECRET_NAME} in namespace ${NAMESPACE}: ${updated_keys[*]}"
