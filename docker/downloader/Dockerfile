FROM python:3.11.17-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR="/tmp" \
    HOME="/tmp" \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    HF_HUB_DOWNLOAD_TIMEOUT=120 \
    HF_HUB_ETAG_TIMEOUT=60

RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -m -s /sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --no-deps -r requirements.txt && \
    python -m pip check && \
    pip uninstall -y pip setuptools wheel && \
    rm -rf /root/.cache /tmp/*

COPY --chown=1000:1000 download_model.py .
RUN chmod 0550 /app/download_model.py && rm -f /app/requirements.txt

USER 1000:1000

ENTRYPOINT ["python", "/app/download_model.py"]
