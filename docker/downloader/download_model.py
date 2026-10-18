#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")

from huggingface_hub import snapshot_download

SAFE_ALLOW_PATTERNS = [
    "*.json",
    "*.safetensors",
    "*.model",
    "tokenizer*",
    "*.txt",
    "*.tiktoken",
    "*.jinja",
]


def parse_download_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-id",
        type=str,
        default=os.environ.get("MODEL_ID"),
    )
    parser.add_argument(
        "--revision",
        type=str,
        default=os.environ.get("MODEL_REVISION"),
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=os.environ.get("MODEL_CACHE_DIR", "/models"),
    )
    return parser.parse_args()


def read_huggingface_token_from_env() -> str | None:
    raw_token = os.environ.get("HF_TOKEN", "").strip()
    return raw_token or None


def validate_model_artifacts(target_model_directory: Path) -> bool:
    if not target_model_directory.is_dir():
        return False

    config_file = target_model_directory / "config.json"
    if not config_file.is_file():
        return False

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if not isinstance(cfg, dict) or ("model_type" not in cfg and "architectures" not in cfg):
                return False
    except Exception:
        return False

    safetensors = list(target_model_directory.glob("*.safetensors"))
    if not safetensors or not any(w.stat().st_size > 10 * 1024 * 1024 for w in safetensors):
        return False

    has_tokenizer = (
        (target_model_directory / "tokenizer.json").is_file()
        or (target_model_directory / "tokenizer_config.json").is_file()
    )
    return has_tokenizer


def is_model_already_cached(target_model_directory: Path, completion_marker_path: Path) -> bool:
    if not completion_marker_path.exists():
        return False
    return validate_model_artifacts(target_model_directory)


def download_with_retry(
    model_id: str,
    revision: str | None,
    staging_dir: Path,
    token: str | None,
    max_attempts: int = 3,
) -> None:
    staging_dir.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"INFO: Download attempt {attempt}/{max_attempts} for '{model_id}' (revision: {revision or 'default'})...")
            snapshot_download(
                repo_id=model_id,
                revision=revision,
                local_dir=str(staging_dir),
                token=token,
                max_workers=2,
                allow_patterns=SAFE_ALLOW_PATTERNS,
            )
            return
        except Exception as err:
            print(f"WARNING: Attempt {attempt} failed: {err}", file=sys.stderr)
            if attempt == max_attempts:
                raise
            sleep_duration = 5 * attempt
            print(f"INFO: Waiting {sleep_duration}s before retry...")
            time.sleep(sleep_duration)


def download_and_cache_model_weights() -> None:
    arguments = parse_download_arguments()
    raw_model_id = (arguments.model_id or "").strip().replace("\r", "")
    cache_directory = Path(arguments.cache_dir)
    revision = (arguments.revision or "").strip() or None
    huggingface_token = read_huggingface_token_from_env()

    if not raw_model_id or raw_model_id == "." or ".." in raw_model_id or not re.match(r"^[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)*$", raw_model_id):
        print(f"ERROR: Invalid or unsafe Model ID specified: '{raw_model_id}'", file=sys.stderr)
        sys.exit(1)

    model_id = raw_model_id

    try:
        usage = shutil.disk_usage(cache_directory)
        if usage.free < 2 * 1024 * 1024 * 1024:
            print(f"WARNING: Low disk space on {cache_directory}: {usage.free // (1024*1024)} MB available.", file=sys.stderr)
    except Exception as disk_err:
        print(f"DEBUG: Could not check disk usage: {disk_err}", file=sys.stderr)

    sanitized_model_directory_name = model_id.replace("/", "--").replace("\\", "--")
    target_model_directory = cache_directory / sanitized_model_directory_name
    completion_marker_path = target_model_directory / ".download_complete"

    if is_model_already_cached(target_model_directory, completion_marker_path):
        print(f"INFO: Model '{model_id}' found in local cache ({target_model_directory}). Skipping network download.")
        sys.exit(0)

    staging_dir = cache_directory / f".tmp-{sanitized_model_directory_name}-{os.getpid()}"
    print(f"INFO: Downloading model '{model_id}' from Hugging Face into staging directory...")

    try:
        download_with_retry(model_id, revision, staging_dir, huggingface_token)

        if not validate_model_artifacts(staging_dir):
            raise RuntimeError("Downloaded model artifacts in staging directory failed integrity check.")

        staging_marker = staging_dir / ".download_complete"
        staging_marker.touch()

        if target_model_directory.exists():
            shutil.rmtree(target_model_directory)
        staging_dir.rename(target_model_directory)

        print(f"INFO: Model '{model_id}' successfully verified, published to {target_model_directory}, and cached.")
    except Exception as download_error:
        print(f"ERROR: Failed to download model '{model_id}': {download_error}", file=sys.stderr)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        sys.exit(1)


if __name__ == "__main__":
    download_and_cache_model_weights()
