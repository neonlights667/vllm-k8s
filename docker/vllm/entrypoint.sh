#!/usr/bin/env bash
set -euo pipefail

: "${VLLM_API_KEY:?ERROR: VLLM_API_KEY environment variable must be set and non-empty}"

MODEL_ID="$(echo "${MODEL_ID:-Qwen/Qwen3.5-0.8B}" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
CACHE_DIR="${MODEL_CACHE_DIR:-/models}"
FORMATTED_MODEL_ID="${MODEL_ID//\//--}"
LOCAL_MODEL_PATH="${CACHE_DIR}/${FORMATTED_MODEL_ID}"

echo "INFO: Checking cached model at ${LOCAL_MODEL_PATH}..."

if [ ! -f "${LOCAL_MODEL_PATH}/.download_complete" ]; then
    echo "ERROR: Cached model marker not found at ${LOCAL_MODEL_PATH}/.download_complete" >&2
    echo "ERROR: Ensure that model download finished successfully." >&2
    exit 1
fi

echo "INFO: Starting vLLM OpenAI API server on ${HOST:-0.0.0.0}:${PORT:-8000} for model ${MODEL_ID}..."

SERVER_ARGS=(
    --served-model-name "${MODEL_ID}"
    --host "${HOST:-0.0.0.0}"
    --port "${PORT:-8000}"
    --dtype "${DTYPE:-bfloat16}"
    --max-model-len "${MAX_MODEL_LEN:-2048}"
    --enforce-eager
    --disable-log-stats
    --enable-log-requests
    --language-model-only
    --default-chat-template-kwargs '{"enable_thinking": false}'
    --api-key "${VLLM_API_KEY}"
)

exec vllm serve "${LOCAL_MODEL_PATH}" "${SERVER_ARGS[@]}"
