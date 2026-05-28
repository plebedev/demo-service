#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DEPLOY_TARGET="${DEPLOY_TARGET:-}"
DEPLOY_PATH="${DEPLOY_PATH:-/home/ubuntu/backend-api-deploy}"
SSH_OPTS="${SSH_OPTS:-}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-backend-api}"
TEXT_TOOLS_IMAGE_REPOSITORY="${TEXT_TOOLS_IMAGE_REPOSITORY:-demo-text-tools}"
RUST_SBC_IMAGE_REPOSITORY="${RUST_SBC_IMAGE_REPOSITORY:-demo-rust-sbc-gateway}"
SERVICE="${SERVICE:-backend-api}"
IMAGE_TAG="${1:-${IMAGE_TAG:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD)}}"
BACKEND_IMAGE_ARCHIVE_NAME="${BACKEND_IMAGE_ARCHIVE_NAME:-${IMAGE_ARCHIVE_NAME:-image-${IMAGE_TAG}.tar}}"
TEXT_TOOLS_IMAGE_ARCHIVE_NAME="${TEXT_TOOLS_IMAGE_ARCHIVE_NAME:-text-tools-image-${IMAGE_TAG}.tar}"
RUST_SBC_IMAGE_ARCHIVE_NAME="${RUST_SBC_IMAGE_ARCHIVE_NAME:-rust-sbc-gateway-image-${IMAGE_TAG}.tar}"
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

SERVICE="${SERVICE}" \
IMAGE_REPOSITORY="${IMAGE_REPOSITORY}" \
TEXT_TOOLS_IMAGE_REPOSITORY="${TEXT_TOOLS_IMAGE_REPOSITORY}" \
RUST_SBC_IMAGE_REPOSITORY="${RUST_SBC_IMAGE_REPOSITORY}" \
BACKEND_IMAGE_ARCHIVE_NAME="${BACKEND_IMAGE_ARCHIVE_NAME}" \
TEXT_TOOLS_IMAGE_ARCHIVE_NAME="${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}" \
RUST_SBC_IMAGE_ARCHIVE_NAME="${RUST_SBC_IMAGE_ARCHIVE_NAME}" \
bash "${SCRIPT_DIR}/save-image.sh" "${IMAGE_TAG}" >/dev/null

case "${SERVICE}" in
  backend-api)
    cp "${REPO_ROOT}/dist/${BACKEND_IMAGE_ARCHIVE_NAME}" "${TEMP_DIR}/${BACKEND_IMAGE_ARCHIVE_NAME}"
    ;;
  text-tools)
    cp "${REPO_ROOT}/dist/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}" "${TEMP_DIR}/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}"
    ;;
  rust-sbc-gateway)
    cp "${REPO_ROOT}/dist/${RUST_SBC_IMAGE_ARCHIVE_NAME}" "${TEMP_DIR}/${RUST_SBC_IMAGE_ARCHIVE_NAME}"
    ;;
  all)
    cp "${REPO_ROOT}/dist/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}" "${TEMP_DIR}/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}"
    cp "${REPO_ROOT}/dist/${RUST_SBC_IMAGE_ARCHIVE_NAME}" "${TEMP_DIR}/${RUST_SBC_IMAGE_ARCHIVE_NAME}"
    cp "${REPO_ROOT}/dist/${BACKEND_IMAGE_ARCHIVE_NAME}" "${TEMP_DIR}/${BACKEND_IMAGE_ARCHIVE_NAME}"
    ;;
  *)
    echo "Unknown SERVICE: ${SERVICE}. Use backend-api, text-tools, rust-sbc-gateway, or all."
    exit 1
    ;;
esac

git -C "${REPO_ROOT}" archive --format=tar.gz -o "${TEMP_DIR}/${SOURCE_ARCHIVE_NAME}" HEAD

ssh ${SSH_OPTS} "${DEPLOY_TARGET}" "mkdir -p '${DEPLOY_PATH}/releases' '${DEPLOY_PATH}/artifacts/images' '${DEPLOY_PATH}/artifacts/source'"
scp ${SSH_OPTS} "${TEMP_DIR}/${SOURCE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/source/${SOURCE_ARCHIVE_NAME}"
case "${SERVICE}" in
  backend-api)
    scp ${SSH_OPTS} "${TEMP_DIR}/${BACKEND_IMAGE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/images/${BACKEND_IMAGE_ARCHIVE_NAME}"
    ;;
  text-tools)
    scp ${SSH_OPTS} "${TEMP_DIR}/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/images/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}"
    ;;
  rust-sbc-gateway)
    scp ${SSH_OPTS} "${TEMP_DIR}/${RUST_SBC_IMAGE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/images/${RUST_SBC_IMAGE_ARCHIVE_NAME}"
    ;;
  all)
    scp ${SSH_OPTS} "${TEMP_DIR}/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/images/${TEXT_TOOLS_IMAGE_ARCHIVE_NAME}"
    scp ${SSH_OPTS} "${TEMP_DIR}/${RUST_SBC_IMAGE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/images/${RUST_SBC_IMAGE_ARCHIVE_NAME}"
    scp ${SSH_OPTS} "${TEMP_DIR}/${BACKEND_IMAGE_ARCHIVE_NAME}" "${DEPLOY_TARGET}:${DEPLOY_PATH}/artifacts/images/${BACKEND_IMAGE_ARCHIVE_NAME}"
    ;;
esac
