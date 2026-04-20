#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RELEASE_NAME="${RELEASE_NAME:-backend-api}"
NAMESPACE="${NAMESPACE:-demo}"
VALUES_FILE="${VALUES_FILE:-${REPO_ROOT}/deploy/helm/backend-api/values-demo.yaml}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-backend-api}"
DEPLOY_TARGET="${DEPLOY_TARGET:-}"
DEPLOY_PATH="${DEPLOY_PATH:-/home/ubuntu/backend-api-deploy}"
SSH_OPTS="${SSH_OPTS:-}"
KEEP_REMOTE_RELEASES="${KEEP_REMOTE_RELEASES:-3}"

OPERATIONAL_PATHS=(
  .dockerignore
  .env.example
  .gitignore
  Dockerfile
  Taskfile.yml
  alembic.ini
  alembic
  app
  deploy
  local
  pyproject.toml
)

if [[ -z "${DEPLOY_TARGET}" ]]; then
  echo "DEPLOY_TARGET is required."
  exit 1
fi

if ! git -C "${REPO_ROOT}" rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "Commit the repo first so the image tag can use the current commit hash."
  exit 1
fi

DIRTY_STATUS="$(git -C "${REPO_ROOT}" status --short -- "${OPERATIONAL_PATHS[@]}")"
if [[ -n "${DIRTY_STATUS}" ]]; then
  echo "Refusing to deploy because operational files have uncommitted changes:"
  echo "${DIRTY_STATUS}"
  exit 1
fi

if [[ "${VALUES_FILE}" != /* ]]; then
  VALUES_FILE="${REPO_ROOT}/${VALUES_FILE}"
fi

IMAGE_TAG="${IMAGE_TAG:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD)}"
SOURCE_ARCHIVE_NAME="${SOURCE_ARCHIVE_NAME:-source-${IMAGE_TAG}.tgz}"
IMAGE_ARCHIVE_NAME="${IMAGE_ARCHIVE_NAME:-image-${IMAGE_TAG}.tar}"
REMOTE_RELEASE_DIR="${DEPLOY_PATH}/releases/${IMAGE_TAG}"

echo "Running local checks"
PYTHONPYCACHEPREFIX=/tmp/backend-api-pyc python3 -m compileall "${REPO_ROOT}/app" "${REPO_ROOT}/alembic"
helm lint "${REPO_ROOT}/deploy/helm/backend-api"

bash "${SCRIPT_DIR}/build-image.sh" "${IMAGE_TAG}"
bash "${SCRIPT_DIR}/copy-deploy-bundle.sh" "${IMAGE_TAG}"

ssh ${SSH_OPTS} "${DEPLOY_TARGET}" \
  "cd '${DEPLOY_PATH}' && \
   rm -rf '${REMOTE_RELEASE_DIR}' && \
   mkdir -p '${REMOTE_RELEASE_DIR}' && \
   tar -xzf './artifacts/source/${SOURCE_ARCHIVE_NAME}' -C '${REMOTE_RELEASE_DIR}' && \
   chmod +x '${REMOTE_RELEASE_DIR}/deploy/scripts/remote-deploy.sh' && \
   SOURCE_ARCHIVE_NAME='${SOURCE_ARCHIVE_NAME}' \
   IMAGE_ARCHIVE_NAME='${IMAGE_ARCHIVE_NAME}' \
   RELEASE_NAME='${RELEASE_NAME}' \
   NAMESPACE='${NAMESPACE}' \
   VALUES_FILE='${VALUES_FILE##${REPO_ROOT}/}' \
   IMAGE_REPOSITORY='${IMAGE_REPOSITORY}' \
   IMAGE_TAG='${IMAGE_TAG}' \
   RELEASE_DIR='${REMOTE_RELEASE_DIR}' \
   KEEP_REMOTE_RELEASES='${KEEP_REMOTE_RELEASES}' \
   bash '${REMOTE_RELEASE_DIR}/deploy/scripts/remote-deploy.sh'"
