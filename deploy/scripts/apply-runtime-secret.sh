#!/usr/bin/env bash
set -euo pipefail

SECRET_NAME="${SECRET_NAME:-backend-api-secrets}"
NAMESPACE="${NAMESPACE:-demo}"
DB_PASSWORD="${DB_PASSWORD:-}"
ACCESS_TOKEN_SIGNING_KEY="${ACCESS_TOKEN_SIGNING_KEY:-}"
ADMIN_API_SECRET="${ADMIN_API_SECRET:-}"

if [[ -z "${DB_PASSWORD}" ]]; then
  echo "DB_PASSWORD is required."
  exit 1
fi

if [[ -z "${ACCESS_TOKEN_SIGNING_KEY}" ]]; then
  echo "ACCESS_TOKEN_SIGNING_KEY is required."
  exit 1
fi

if [[ -z "${ADMIN_API_SECRET}" ]]; then
  echo "ADMIN_API_SECRET is required."
  exit 1
fi

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

kubectl create secret generic "${SECRET_NAME}" \
  --namespace "${NAMESPACE}" \
  --from-literal=DB_PASSWORD="${DB_PASSWORD}" \
  --from-literal=ACCESS_TOKEN_SIGNING_KEY="${ACCESS_TOKEN_SIGNING_KEY}" \
  --from-literal=ADMIN_API_SECRET="${ADMIN_API_SECRET}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Applied secret ${SECRET_NAME} in namespace ${NAMESPACE}"
