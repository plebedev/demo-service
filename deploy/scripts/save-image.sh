#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-backend-api}"
TEXT_TOOLS_IMAGE_REPOSITORY="${TEXT_TOOLS_IMAGE_REPOSITORY:-demo-text-tools}"
SERVICE="${SERVICE:-backend-api}"
IMAGE_TAG="${1:-${IMAGE_TAG:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD)}}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/dist}"

mkdir -p "${OUTPUT_DIR}"

save_backend_api() {
  local archive_name="${BACKEND_IMAGE_ARCHIVE_NAME:-${IMAGE_ARCHIVE_NAME:-image-${IMAGE_TAG}.tar}}"
  docker save -o "${OUTPUT_DIR}/${archive_name}" "${IMAGE_REPOSITORY}:${IMAGE_TAG}"
  echo "${OUTPUT_DIR}/${archive_name}"
}

save_text_tools() {
  local archive_name="${TEXT_TOOLS_IMAGE_ARCHIVE_NAME:-text-tools-image-${IMAGE_TAG}.tar}"
  docker save -o "${OUTPUT_DIR}/${archive_name}" "${TEXT_TOOLS_IMAGE_REPOSITORY}:${IMAGE_TAG}"
  echo "${OUTPUT_DIR}/${archive_name}"
}

case "${SERVICE}" in
  backend-api)
    save_backend_api
    ;;
  text-tools)
    save_text_tools
    ;;
  all)
    save_text_tools
    save_backend_api
    ;;
  *)
    echo "Unknown SERVICE: ${SERVICE}. Use backend-api, text-tools, or all."
    exit 1
    ;;
esac
