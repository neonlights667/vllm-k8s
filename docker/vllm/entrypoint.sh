#!/usr/bin/env bash
set -euo pipefail

: "${VLLM_API_KEY:?ERROR: VLLM_API_KEY environment variable must be set and non-empty}"

if [ "${#VLLM_API_KEY}" -lt 16 ]; then
    echo "ERROR: VLLM_API_KEY must be at least 16 characters" >&2
    exit 1
fi

MODEL_ID="$(echo "${MODEL_ID:-Qwen/Qwen3.5-0.8B}" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
CACHE_DIR="${MODEL_CACHE_DIR:-/models}"
FORMATTED_MODEL_ID="${MODEL_ID//\//--}"
LOCAL_MODEL_PATH="${CACHE_DIR}/${FORMATTED_MODEL_ID}"

echo "INFO: Checking cached model at ${LOCAL_MODEL_PATH}..."

if [ ! -f "${LOCAL_MODEL_PATH}/.download_complete" ]; then
    echo "ERROR: Cached model marker not found at ${LOCAL_MODEL_PATH}/.download_complete" >&2
    echo "ERROR: Ensure that initContainer (model-downloader) finished successfully." >&2
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
    --disable-access-log-for-endpoints "/health"
    --default-chat-template-kwargs '{"enable_thinking": false}'
    --middleware auth_middleware.StrictAuthMiddleware
)

if [ -n "${EXTRA_ARGS:-}" ]; then
    while IFS= read -r -d '' arg; do
        SERVER_ARGS+=("$arg")
    done < <(python3 -c '
import sys, shlex, re
disallowed = re.compile(r"^--?(?:api|trust|model|port|host|middleware|logging|enable-log|config)", re.IGNORECASE)
args = shlex.split(sys.argv[1])
for a in args:
    if a.startswith("-"):
        norm = a.split("=")[0].replace("_", "-")
        if disallowed.match(norm):
            sys.exit(f"ERROR: Disallowed parameter in EXTRA_ARGS: \"{a}\". Cannot override core security flags.")
for a in args:
    sys.stdout.write(a + "\0")
' "${EXTRA_ARGS}")
fi

exec vllm serve "${LOCAL_MODEL_PATH}" "${SERVER_ARGS[@]}"
