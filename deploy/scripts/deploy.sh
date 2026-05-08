#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RELEASE_NAME="${RELEASE_NAME:-backend-api}"
TEXT_TOOLS_RELEASE_NAME="${TEXT_TOOLS_RELEASE_NAME:-demo-text-tools}"
NAMESPACE="${NAMESPACE:-demo}"
VALUES_FILE="${VALUES_FILE:-${REPO_ROOT}/deploy/helm/backend-api/values-demo.yaml}"
TEXT_TOOLS_VALUES_FILE="${TEXT_TOOLS_VALUES_FILE:-${REPO_ROOT}/deploy/helm/text-tools/values-demo.yaml}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-backend-api}"
TEXT_TOOLS_IMAGE_REPOSITORY="${TEXT_TOOLS_IMAGE_REPOSITORY:-demo-text-tools}"
SERVICE="${SERVICE:-backend-api}"
IMAGE_TAG="${1:-${IMAGE_TAG:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD)}}"
CHART_DIR="${REPO_ROOT}/deploy/helm/backend-api"
TEXT_TOOLS_CHART_DIR="${REPO_ROOT}/deploy/helm/text-tools"

deploy_backend_api() {
  if [[ ! -f "${VALUES_FILE}" ]]; then
    echo "Values file not found: ${VALUES_FILE}"
    exit 1
  fi

  helm upgrade --install "${RELEASE_NAME}" "${CHART_DIR}" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    -f "${CHART_DIR}/values.yaml" \
    -f "${VALUES_FILE}" \
    --set-string namespace="${NAMESPACE}" \
    --set-string image.repository="${IMAGE_REPOSITORY}" \
    --set-string image.tag="${IMAGE_TAG}" \
    --wait \
    --timeout 5m
}

deploy_text_tools() {
  if [[ ! -f "${TEXT_TOOLS_VALUES_FILE}" ]]; then
    echo "Values file not found: ${TEXT_TOOLS_VALUES_FILE}"
    exit 1
  fi

  helm upgrade --install "${TEXT_TOOLS_RELEASE_NAME}" "${TEXT_TOOLS_CHART_DIR}" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    -f "${TEXT_TOOLS_CHART_DIR}/values.yaml" \
    -f "${TEXT_TOOLS_VALUES_FILE}" \
    --set-string namespace="${NAMESPACE}" \
    --set-string image.repository="${TEXT_TOOLS_IMAGE_REPOSITORY}" \
    --set-string image.tag="${IMAGE_TAG}" \
    --wait \
    --timeout 5m
}

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

case "${SERVICE}" in
  backend-api)
    deploy_backend_api
    ;;
  text-tools)
    deploy_text_tools
    ;;
  all)
    deploy_text_tools
    deploy_backend_api
    ;;
  *)
    echo "Unknown SERVICE: ${SERVICE}. Use backend-api, text-tools, or all."
    exit 1
    ;;
esac
