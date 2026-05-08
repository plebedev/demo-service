#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-backend-api}"
TEXT_TOOLS_IMAGE_REPOSITORY="${TEXT_TOOLS_IMAGE_REPOSITORY:-demo-text-tools}"
SERVICE="${SERVICE:-backend-api}"
IMAGE_TAG="${1:-${IMAGE_TAG:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD)}}"

build_backend_api() {
  echo "Building ${IMAGE_REPOSITORY}:${IMAGE_TAG}"
  docker build -t "${IMAGE_REPOSITORY}:${IMAGE_TAG}" "${REPO_ROOT}"
}

build_text_tools() {
  echo "Building ${TEXT_TOOLS_IMAGE_REPOSITORY}:${IMAGE_TAG}"
  docker build \
    -f "${REPO_ROOT}/text-tools/Dockerfile" \
    -t "${TEXT_TOOLS_IMAGE_REPOSITORY}:${IMAGE_TAG}" \
    "${REPO_ROOT}"
}

case "${SERVICE}" in
  backend-api)
    build_backend_api
    ;;
  text-tools)
    build_text_tools
    ;;
  all)
    build_text_tools
    build_backend_api
    ;;
  *)
    echo "Unknown SERVICE: ${SERVICE}. Use backend-api, text-tools, or all."
    exit 1
    ;;
esac
