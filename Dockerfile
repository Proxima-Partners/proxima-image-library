# Matching Docker Hardened Python 3.12.15 / Debian 13 images. Update both
# digests by reviewed PR; the minimal image still has to pass the scan gate.
ARG PYTHON_BUILD_IMAGE=dhi.io/python:3.12-debian13-dev@sha256:a3d43f90a9e72d5fa53efa18c692f020604c95e89bc7de62aa9cafad7ee9c795
ARG PYTHON_RUNTIME_IMAGE=dhi.io/python:3.12-debian13@sha256:a67245096d56c6ce891b9bec78a8090850907af9314185597c6b5d75438ca999
FROM ${PYTHON_BUILD_IMAGE} AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN python -m venv --without-pip /opt/venv
COPY requirements.txt ./
# Use the builder's pip; do not add it to the application virtual environment.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip --python /opt/venv install --only-binary=:all: -r requirements.txt && \
    python -m pip --python /opt/venv check

FROM dependencies AS test-dependencies
COPY requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip --python /opt/venv install --only-binary=:all: \
      --constraint requirements.txt --requirement requirements-dev.txt && \
    python -m pip --python /opt/venv check

FROM dependencies AS source
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY templates/ ./templates/
COPY static/ ./static/

FROM source AS identified
ARG COMMIT_SHA
ARG BUILD_ID
RUN /opt/venv/bin/python scripts/write_build_info.py --commit "$COMMIT_SHA" --build-id "$BUILD_ID"

FROM ${PYTHON_RUNTIME_IMAGE} AS runtime-base
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PORT=8080 APP_STATE_DIR=/home \
    TAG_LIBRARY_PATH=/home/tag_library.json APP_READ_ONLY=true \
    INGEST_POLLER_ENABLED=false TEST_MODE=false DEV_AUTH_BYPASS=false
# Build-time ownership only. The vendor's nonroot identity remains the runtime
# user. Azure's mount replaces these modes/owners; separately prove worker access
# and keep credentials environment-only rather than claiming POSIX privacy there.
USER 0
RUN ["python", "-c", "import os; os.chown('/home', 65532, 65532)"]
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=source /app /app
USER 65532:65532
EXPOSE 8080
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opt/venv/bin/python", "-m", "scripts.container_start"]
CMD []

# Execute the suite on the SAME shellless OS/runtime and non-root identity, not
# on the dev image. Only this discarded stage receives tests and test tools.
FROM runtime-base AS test
COPY --from=test-dependencies /opt/venv /opt/venv
COPY tests/ ./tests/
USER 0
RUN ["python", "-c", "import os; os.mkdir('/app/test_data'); os.chown('/app/test_data', 65532, 65532)"]
USER 65532:65532
ENV TEST_MODE=true DEV_AUTH_BYPASS=true STORAGE_MODE=local APP_READ_ONLY=false \
    TELEMETRY_ENABLED=false PYTHON_DOTENV_DISABLED=1 \
    FLASK_SECRET_KEY=container-test-only-secret-0000000000
RUN --network=none ["python", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]

FROM runtime-base AS runtime
ARG COMMIT_SHA
ARG BUILD_ID
LABEL org.opencontainers.image.title="Proxima Image Library" \
      org.opencontainers.image.source="https://github.com/Proxima-Partners/proxima-image-library" \
      org.opencontainers.image.revision=$COMMIT_SHA \
      org.opencontainers.image.version=$BUILD_ID
COPY --from=identified /app/build_info.json /app/build_info.json
