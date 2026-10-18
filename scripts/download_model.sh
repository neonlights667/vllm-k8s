#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "${SCRIPT_DIR}/../docker/downloader/download_model.py" \
  --model-id "${1:-${MODEL_ID:-Qwen/Qwen3.5-0.8B}}" \
  --cache-dir "${2:-${MODEL_CACHE_DIR:-./models}}"
