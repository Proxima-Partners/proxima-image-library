# Unattended implementation journal

Approved 2026-10-23. Branch: `perf/unattended-operations`, based on accepted
container checkpoint `e6ca9f7`. Implementation, tests, branch commits/pushes and
build-only CI are approved. Main integration, deployment, access changes, live
write tests and schedule activation are separate approval gates.

## Current handoff: 2026-10-24 04:41 UTC / October 23 PDT

**Implementation scope passed build-only CI and is pushed. Production activation
is not authorized or enabled.** The signed implementation commit is
`426f475d8e73a24959a90cefbb58ec4b13eae7e8` on `perf/unattended-operations`.
[CI run 40063209524](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/40063209524)
completed successfully; the container job took 1m13s. Its logs confirm **633
target-runtime tests**, **12 browser/workflow checks**, exact-image runtime and
release-channel smoke, SBOM and security gate all passed. Zero unreviewed
HIGH/CRITICAL findings; existing reviewed exceptions remain unchanged.

Evidence artifact `12548377289` / `container-validation-40063209524-1` is retained,
digest `sha256:f657e1445f402dca2e12d6cec41f8fb1a631b6171bd29b13f4caffc2ee720352`.
The job is open in Microsoft Edge. A fresh 04:40 UTC four-request public probe
passed against accepted production `2ffc0ff` / `40019125172-1`; pilot mode is
still `hold`, the legacy workflow is `disabled_manually`, and remote `main` is
still `0ddfd05`. No deployment, Azure mutation, write canary or schedule activation.
The 24-hour telemetry and representative-performance gates remain open.

CI reported a non-failing compatibility warning for the pinned
`actions/upload-artifact` action declaring Node 20 while the runner uses Node 24.
Artifact upload succeeded. Review/update the pinned action in the next dependency
batch before production automation activation; do not suppress the warning.
Next approval boundary: reviewed main integration, then separately scoped CI
access and isolated recovery rehearsal as listed in `OPERATIONS_ACTIVATION.md`.

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
- Batch 2 CI `40029611544` passed all build-only gates.
- Batch 3: authenticated exact-build artifact retrieval, bounded ARM status/
  Location polling with Retry-After, and dual-opt-in exact-runtime idle resume.
  Ambiguous mutation/resume cannot trigger retries or rollback. Default remains
  drained after promotion. Real accepted artifact `12529602290` was verified
  read-only against run `40019125172-1`; no deployment or fresh scan was implied.
- Batch 4: manual, main-only, opt-in public-health and evidence-review workflows;
  legacy/pilot/source-baseline workflows replaced by refusal stubs on this branch.
  Existing remote default/old branches, access grants and holds are unchanged.
  Four bounded public checks passed at 22:05 UTC against the accepted build.
- Added a target-image asset-presence test and HTTP smoke assertion for the badge
  script, plus five workflow-boundary checks. Actionlint passed all workflows.
  `OPERATIONS_ACTIVATION.md` records activation gates and the proposed maintenance
  cadence. No schedule, alert service, new role or production automation enabled.
- Build-only push validation now skips documentation-only checkpoints. Pull
  request validation stays unconditional; required checks are not path-filtered.
- Final local regression: **633 passed** on the actual Linux/amd64 Python 3.12.15
  nonroot runtime with network disabled; **12 passed** browser/workflow checks.
  Actionlint and `git diff --check` passed. Existing UTC deprecation warnings
  remain visible. Fresh build-only CI is the remaining implementation check.

## Signing checkpoint: 2026-10-23 22:12 UTC (historical; resolved above)

- First two batches are committed/pushed as `a77d642` and `f622521`; their CI runs
  `40029086741` and `40029611544` passed. HEAD remains `f622521`.
- Final batch is implemented, tested and staged, **not committed or pushed**.
  The configured 1Password SSH signer failed with `failed to fill whole buffer`;
  Git reported `failed to write commit object`. No signing bypass or Git config
  change was attempted, and no commit/signing process remains running.
- Offline exact-runtime smoke and release-channel smoke passed after the final
  changes, including fresh boot, persistent drain, stale-boot rejection and opt-in
  idle resume. The local fixture uses zero commit / `local-unattended-1`, explicitly
  not a deployable CI release identity.
- Fresh local Trivy scan/SBOM/security gate passed: zero **unreviewed** HIGH/CRITICAL
  findings; the existing eight exact reviewed findings remain. No exception was
  added or expiry extended. Evidence is in
  `/private/tmp/image-library-unattended-scan.tFXaEN/reports/`; this temporary local
  evidence does not replace a trusted fresh CI build of the eventual commit.
- Next: user unlocks/authorizes 1Password signing; retry this branch's commit,
  push only `perf/unattended-operations`, then observe fresh build-only CI through
  its full security/runtime gates. Do not rerun a deployed workflow or bypass
  signing. Production/main/schedules/access remain unchanged.

## Activation gates (not granted by implementation approval)

Reviewed main integration; CI identity/network proof; least-privilege diagnostic
credentials; isolated live recovery rehearsal; completed post-cutover observation;
first supervised normal release and explicit resume-writes acceptance. Only then
consider opt-in unattended production and scheduled read-only diagnostics.
