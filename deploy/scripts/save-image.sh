#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-backend-api}"
IMAGE_TAG="${1:-${IMAGE_TAG:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD)}}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/dist}"
IMAGE_ARCHIVE_NAME="${IMAGE_ARCHIVE_NAME:-image-${IMAGE_TAG}.tar}"

mkdir -p "${OUTPUT_DIR}"
docker save -o "${OUTPUT_DIR}/${IMAGE_ARCHIVE_NAME}" "${IMAGE_REPOSITORY}:${IMAGE_TAG}"
echo "${OUTPUT_DIR}/${IMAGE_ARCHIVE_NAME}"
