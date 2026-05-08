#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="${RELEASE_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
DEPLOY_ROOT="$(cd "${RELEASE_DIR}/../.." && pwd)"

SOURCE_ARCHIVE_NAME="${SOURCE_ARCHIVE_NAME:-source.tgz}"
BACKEND_IMAGE_ARCHIVE_NAME="${BACKEND_IMAGE_ARCHIVE_NAME:-${IMAGE_ARCHIVE_NAME:-image.tar}}"
TEXT_TOOLS_IMAGE_ARCHIVE_NAME="${TEXT_TOOLS_IMAGE_ARCHIVE_NAME:-text-tools-image.tar}"
RELEASE_NAME="${RELEASE_NAME:-backend-api}"
TEXT_TOOLS_RELEASE_NAME="${TEXT_TOOLS_RELEASE_NAME:-demo-text-tools}"
NAMESPACE="${NAMESPACE:-demo}"
VALUES_FILE="${VALUES_FILE:-deploy/helm/backend-api/values-demo.yaml}"
TEXT_TOOLS_VALUES_FILE="${TEXT_TOOLS_VALUES_FILE:-deploy/helm/text-tools/values-demo.yaml}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-backend-api}"
TEXT_TOOLS_IMAGE_REPOSITORY="${TEXT_TOOLS_IMAGE_REPOSITORY:-demo-text-tools}"
SERVICE="${SERVICE:-backend-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMPORT_IMAGE_COMMAND="${IMPORT_IMAGE_COMMAND:-sudo k3s ctr images import}"
KUBECONFIG_PATH="${KUBECONFIG_PATH:-/etc/rancher/k3s/k3s.yaml}"
KEEP_REMOTE_RELEASES="${KEEP_REMOTE_RELEASES:-3}"

if [[ -z "${IMAGE_TAG}" ]]; then
  echo "IMAGE_TAG is required."
  exit 1
fi

if [[ ! -f "${DEPLOY_ROOT}/artifacts/source/${SOURCE_ARCHIVE_NAME}" ]]; then
  echo "Source archive not found: ${DEPLOY_ROOT}/artifacts/source/${SOURCE_ARCHIVE_NAME}"
  exit 1
fi

require_image() {
  local archive_name="$1"
  if [[ ! -f "${DEPLOY_ROOT}/artifacts/images/${archive_name}" ]]; then
    echo "Image archive not found: ${DEPLOY_ROOT}/artifacts/images/${archive_name}"
    exit 1
  fi
}

require_values() {
  local values_file="$1"
  if [[ ! -f "${RELEASE_DIR}/${values_file}" ]]; then
    echo "Values file not found after extract: ${RELEASE_DIR}/${values_file}"
    exit 1
  fi
}

deploy_backend_api() {
  require_image "${BACKEND_IMAGE_ARCHIVE_NAME}"
  require_values "${VALUES_FILE}"
  ${IMPORT_IMAGE_COMMAND} "${DEPLOY_ROOT}/artifacts/images/${BACKEND_IMAGE_ARCHIVE_NAME}"

  helm upgrade --install "${RELEASE_NAME}" "${RELEASE_DIR}/deploy/helm/backend-api" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    -f "${RELEASE_DIR}/deploy/helm/backend-api/values.yaml" \
    -f "${RELEASE_DIR}/${VALUES_FILE}" \
    --set-string namespace="${NAMESPACE}" \
    --set-string image.repository="${IMAGE_REPOSITORY}" \
    --set-string image.tag="${IMAGE_TAG}" \
    --set-string image.pullPolicy="IfNotPresent" \
    --wait \
    --timeout 5m

  kubectl get svc,deployment,pods -n "${NAMESPACE}" -l "app.kubernetes.io/instance=${RELEASE_NAME}"
}

deploy_text_tools() {
  require_image "${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}"
  require_values "${TEXT_TOOLS_VALUES_FILE}"
  ${IMPORT_IMAGE_COMMAND} "${DEPLOY_ROOT}/artifacts/images/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}"

  helm upgrade --install "${TEXT_TOOLS_RELEASE_NAME}" "${RELEASE_DIR}/deploy/helm/text-tools" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    -f "${RELEASE_DIR}/deploy/helm/text-tools/values.yaml" \
    -f "${RELEASE_DIR}/${TEXT_TOOLS_VALUES_FILE}" \
    --set-string namespace="${NAMESPACE}" \
    --set-string image.repository="${TEXT_TOOLS_IMAGE_REPOSITORY}" \
    --set-string image.tag="${IMAGE_TAG}" \
    --set-string image.pullPolicy="IfNotPresent" \
    --wait \
    --timeout 5m

  kubectl get svc,deployment,pods -n "${NAMESPACE}" -l "app.kubernetes.io/instance=${TEXT_TOOLS_RELEASE_NAME}"
}

export KUBECONFIG="${KUBECONFIG_PATH}"

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

cleanup_old_artifacts() {
  local keep_count="$1"
  local target_dir="$2"

  if [[ ! -d "${target_dir}" ]]; then
    return 0
  fi

  mapfile -t entries < <(find "${target_dir}" -mindepth 1 -maxdepth 1 -printf '%T@ %P\n' | sort -nr | awk '{print $2}')
  if (( ${#entries[@]} <= keep_count )); then
    return 0
  fi

  for entry in "${entries[@]:keep_count}"; do
    rm -rf "${target_dir}/${entry}"
  done
}

cleanup_old_artifacts "${KEEP_REMOTE_RELEASES}" "${DEPLOY_ROOT}/releases"
cleanup_old_artifacts "${KEEP_REMOTE_RELEASES}" "${DEPLOY_ROOT}/artifacts/images"
cleanup_old_artifacts "${KEEP_REMOTE_RELEASES}" "${DEPLOY_ROOT}/artifacts/source"
