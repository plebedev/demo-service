#!/usr/bin/env bash
set -euo pipefail

RELEASE_NAME="${RELEASE_NAME:-backend-api}"
NAMESPACE="${NAMESPACE:-demo}"
REVISION="${1:-${REVISION:-}}"

if [[ -z "${REVISION}" ]]; then
  helm history "${RELEASE_NAME}" --namespace "${NAMESPACE}"
  exit 0
fi

helm rollback "${RELEASE_NAME}" "${REVISION}" --namespace "${NAMESPACE}" --wait --timeout 5m
