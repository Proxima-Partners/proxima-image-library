#!/usr/bin/env bash
# One validation implementation shared by unprivileged CI and trusted pilot builds.
set -euo pipefail
: "${GITHUB_SHA:?}" "${GITHUB_RUN_ID:?}" "${GITHUB_RUN_ATTEMPT:?}" "${IMAGE:?}" "${TRIVY_IMAGE:?}"
mkdir -p reports scan-input scan-cache
cache_args=()
test_cache_args=()
if [[ -n "${BUILD_CACHE_REF:-}" ]]; then
  cache_args=(--cache-from "type=registry,ref=$BUILD_CACHE_REF" --cache-to "type=registry,ref=$BUILD_CACHE_REF,mode=max")
  test_cache_args=(--cache-from "type=registry,ref=${BUILD_CACHE_REF}-tests" --cache-to "type=registry,ref=${BUILD_CACHE_REF}-tests,mode=max")
fi
docker buildx build --platform linux/amd64 --target test --load \
  "${test_cache_args[@]}" --tag image-library:tests .
docker buildx build --platform linux/amd64 --target runtime --load \
  "${cache_args[@]}" --build-arg "COMMIT_SHA=$GITHUB_SHA" \
  --build-arg "BUILD_ID=$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT" --tag "$IMAGE" .
docker image inspect "$IMAGE" --format '{{json .}}' > reports/image.json
python3 scripts/container_smoke.py "$IMAGE" "$GITHUB_SHA" \
  "$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT" | tee reports/smoke.json
docker save --output scan-input/runtime.tar "$IMAGE"
scanner_args=(--rm --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges
  --volume "$PWD/scan-input:/input:ro" --volume "$PWD/reports:/reports" --volume "$PWD/scan-cache:/cache")
docker run "${scanner_args[@]}" "$TRIVY_IMAGE" image --cache-dir /cache --input /input/runtime.tar \
  --format cyclonedx --output /reports/sbom.cdx.json
set +e
docker run "${scanner_args[@]}" "$TRIVY_IMAGE" image --cache-dir /cache --input /input/runtime.tar \
  --scanners vuln --format json --output /reports/vulnerabilities.json --severity HIGH,CRITICAL --exit-code 42
scan_status=$?
set -e
printf '%s\n' "$scan_status" > reports/raw-scan-exit-code.txt
test "$scan_status" -eq 0 || test "$scan_status" -eq 42
python3 scripts/container_security_gate.py --policy security/container-review.json \
  --scan reports/vulnerabilities.json --archive scan-input/runtime.tar \
  --commit "$GITHUB_SHA" --build-id "$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT" --output reports/security-gate.json
