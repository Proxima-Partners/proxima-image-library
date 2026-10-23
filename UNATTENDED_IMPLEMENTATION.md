# Unattended implementation journal

Approved 2026-10-23. Branch: `perf/unattended-operations`, based on accepted
container checkpoint `e6ca9f7`. Implementation, tests, branch commits/pushes and
build-only CI are approved. Main integration, deployment, access changes, live
write tests and schedule activation are separate approval gates.

## Invariants

- Preserve current production and rollback artifacts. No slot swaps.
- Keep pilot mode `hold`, legacy deployment disabled, ingestion off, one process
  and one instance. Never dispatch the old pilot against writable production.
- Tests use isolated data. Do not infer permission for another production canary.
- A missing or incomplete observation is not a pass. The 24-hour observation
  remains open until actual telemetry and functional evidence are reviewed.
- No secrets, filenames, raw provider errors or protected state hashes in reports.
- New roles/network paths, main merge and production activation require review.

## Batches and exit gates

1. Bounded report-only diagnostics and visibility/auth-aware badge polling.
   Prove request/page/record/byte/time limits, incomplete results and zero writes.
2. Reusable read transport and coordinated catalog cache. Prove invalidation,
   concurrent refresh behavior and no replay of writes. Keep worker mode unchanged.
3. Authenticated artifact verification and fail-closed release-controller
   safeguards. Prove exact run/artifact/image binding and failure recovery locally.
4. Prepare disabled operations workflows and integration instructions. Validate
   workflow boundaries; do not activate schedules or production promotion.
5. Produce the tested handoff and exact remaining activation gates.

## Progress

- Baseline: clean accepted branch; production remains on `2ffc0ff` according to
  cutover records. This journal is not a new live production acceptance report.
- Implementation branch created. No Azure mutations or production data writes.
- Batch 1: bounded diagnostics and badge polling implemented. Target Linux/amd64
  Python 3.12.15, nonroot, network-disabled container suite: **523 passed**.
  Browser polling behavior: **7 passed**. Existing developer `.venv` lacks
  telemetry dependencies; it was left unchanged. The target-image suite is the
  authoritative regression result. Existing UTC deprecation warnings retained.
- Diagnostics are disabled by default and require a separately supplied scoped
  token. Serial reads (concurrency 1), no retries, 300 seconds/1,000 records/
  40 pages/120 requests/3,000 image files/100 folders per tree/20 thumbnail samples,
  2 MiB per response and 20 MiB total. Budget exhaustion is incomplete, not healthy.
  Reference/orphan counts remain unknown unless both inventories finish.
  Counts are point-in-time observations, never authorization for repair/deletion.
- Batch 1 CI `40029086741` passed: target-image regression, smoke, release-channel
  checks, security gate, SBOM and browser behavior. No publish/deploy permissions.
- Batch 2: thread-owned pooled Graph reads; at most one retry for explicit
  429/503/504 responses within the read budget, never a shortened Retry-After.
  Token refresh is serialized. Writes/download semantics are not retried/changed.
  Catalog refresh is single-flight, returns private copies, discards snapshots
  invalidated during a fetch, and invalidates after partial/uncertain writes.
  Five simultaneous fixture reads cause one fetch, not five. This is a request-
  count result, not a live latency benchmark. Worker/process count unchanged.
- Batch 2 target-Linux container: **548 passed**; JS **7 passed**. Reused isolated
  Python 3.12 developer validation: 541 passed/7 Linux-only skipped. Production
  remains unchanged; live concurrency/browser-performance acceptance is pending.

## Activation gates (not granted by implementation approval)

Reviewed main integration; CI identity/network proof; least-privilege diagnostic
credentials; isolated live recovery rehearsal; completed post-cutover observation;
first supervised normal release and explicit resume-writes acceptance. Only then
consider opt-in unattended production and scheduled read-only diagnostics.
