#!/usr/bin/env bash
set -e

# Default values
IMAGE_NAME="${IMAGE_NAME:-chatbob}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="${CONTAINER_NAME:-chatbob}"
PORT="${PORT:-3000}"
API_KEY="${1:-${BOB_API_KEY}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# Ensure config.json exists if mounting
if [ ! -f "config.json" ]; then
  echo "{}" > config.json
fi

# Validate API key
if [ -z "${API_KEY}" ]; then
  echo "Usage: $0 [BOB_API_KEY]"
  echo "Alternatively, export BOB_API_KEY environment variable."
  exit 1
fi

echo "=========================================="
echo " Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "=========================================="
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

# Stop and remove existing container if running
if [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
  echo "Removing existing container '${CONTAINER_NAME}'..."
  docker rm -f "${CONTAINER_NAME}"
fi

echo "=========================================="
echo " Running container: ${CONTAINER_NAME} on port ${PORT}"
echo "=========================================="
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "${PORT}:${PORT}" \
  -e BOB_API_KEY="${API_KEY}" \
  -v "${PWD}/config.json:/app/config.json" \
  "${IMAGE_NAME}:${IMAGE_TAG}"

echo ""
echo "ChatBob deployed successfully! Access it at http://localhost:${PORT}"
