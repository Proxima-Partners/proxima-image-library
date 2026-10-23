# Official Python 3.12.15, Debian trixie; update the digest by reviewed PR.
# This candidate still must pass the OS vulnerability gate before deployment.
ARG PYTHON_IMAGE=python:3.12-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
FROM ${PYTHON_IMAGE} AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --only-binary=:all: -r requirements.txt && python -m pip check

FROM dependencies AS source
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY templates/ ./templates/
COPY static/ ./static/
COPY startup.sh ./

FROM source AS test
COPY requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -r requirements-dev.txt && python -m pip check
COPY tests/ ./tests/
RUN TEST_MODE=true STORAGE_MODE=local APP_READ_ONLY=false INGEST_POLLER_ENABLED=false \
    TELEMETRY_ENABLED=false PYTHON_DOTENV_DISABLED=1 \
    FLASK_SECRET_KEY=container-test-only-secret-0000000000 \
    python -m pytest tests -q

FROM source AS identified
ARG COMMIT_SHA
ARG BUILD_ID
RUN python scripts/write_build_info.py --commit "$COMMIT_SHA" --build-id "$BUILD_ID"

FROM ${PYTHON_IMAGE} AS runtime
ARG COMMIT_SHA
ARG BUILD_ID
LABEL org.opencontainers.image.title="Proxima Image Library" \
      org.opencontainers.image.source="https://github.com/Proxima-Partners/proxima-image-library" \
      org.opencontainers.image.revision=$COMMIT_SHA \
      org.opencontainers.image.version=$BUILD_ID
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PORT=8080 APP_STATE_DIR=/home \
    TAG_LIBRARY_PATH=/home/tag_library.json APP_READ_ONLY=true \
    INGEST_POLLER_ENABLED=false TEST_MODE=false DEV_AUTH_BYPASS=false
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 \
    --no-create-home --home-dir /home --shell /usr/sbin/nologin app && chown app:app /home
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=identified /app /app
USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM
CMD ["bash", "startup.sh"]
