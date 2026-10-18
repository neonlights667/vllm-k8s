FROM vllm/vllm-openai-cpu:v0.31.0@sha256:495c84fe30f3572b83a78100a1e8ba423dbb77fc532ecefebe114e6b77327bd9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app" \
    TMPDIR="/tmp" \
    HOME="/tmp" \
    VLLM_TARGET_DEVICE=cpu \
    VLLM_CONFIGURE_LOGGING=1 \
    VLLM_LOGGING_CONFIG_PATH="/app/logging_config.json" \
    HF_HUB_OFFLINE=1 \
    VLLM_NO_USAGE_STATS=1 \
    DO_NOT_TRACK=1

USER root
RUN groupadd -g 1000 appgroup 2>/dev/null || true && \
    useradd -u 1000 -g appgroup -m -s /sbin/nologin appuser 2>/dev/null || true && \
    python3 -m pip check

WORKDIR /app
COPY --chown=root:root --chmod=0555 privacy_filter.py logging_config.json entrypoint.sh requirements.txt /app/

USER 1000:1000
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
