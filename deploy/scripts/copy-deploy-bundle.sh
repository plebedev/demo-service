#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DEPLOY_TARGET="${DEPLOY_TARGET:-}"
DEPLOY_PATH="${DEPLOY_PATH:-/home/ubuntu/backend-api-deploy}"
SSH_OPTS="${SSH_OPTS:-}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-backend-api}"
IMAGE_TAG="${1:-${IMAGE_TAG:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD)}}"
IMAGE_ARCHIVE_NAME="${IMAGE_ARCHIVE_NAME:-image-${IMAGE_TAG}.tar}"
SOURCE_ARCHIVE_NAME="${SOURCE_ARCHIVE_NAME:-source-${IMAGE_TAG}.tgz}"

if [[ -z "${DEPLOY_TARGET}" ]]; then
  echo "DEPLOY_TARGET is required."
  exit 1
fi

TEMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

bash "${SCRIPT_DIR}/save-image.sh" "${IMAGE_TAG}" >/dev/null
cp "${REPO_ROOT}/dist/${IMAGE_ARCHIVE_NAME}" "${TEMP_DIR}/${IMAGE_ARCHIVE_NAME}"
git -C "${REPO_ROOT}" archive --format=tar.gz -o "${TEMP_DIR}/${SOURCE_ARCHIVE_NAME}" HEAD

ssh ${SSH_OPTS} "${DEPLOY_TARGET}" "mkdir -p '${DEPLOY_PATH}/releases' '${DEPLOY_PATH}/artifacts/images' '${DEPLOY_PATH}/artifacts/source'"
scp ${SSH_OPTS} "${TEMP_DIR}/${SOURCE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/source/${SOURCE_ARCHIVE_NAME}"
scp ${SSH_OPTS} "${TEMP_DIR}/${IMAGE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/images/${IMAGE_ARCHIVE_NAME}"
