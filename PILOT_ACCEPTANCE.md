# Container pilot acceptance evidence

As of 2026-10-23 PDT. **Isolated read-only pilot PASSED with in-place promotion.**
The pilot evidence below is historical. The subsequent supervised public cutover
also passed; the custom domain now serves writable v2.0.0. See
`cutover-evidence/2026-10-23-production-cutover.json` and
`PRODUCTION_RELEASE_RUNBOOK.md` for current state and remaining automation gates.

## Final acceptance — 2026-10-23

**PASS for the isolated, read-only container pilot using in-place promotion.**
This does not authorize or claim a completed public production cutover.

Five fresh workflows passed, with 255 tests actually executed on each attempt,
exact-image smoke, SBOM/security gates, immutable publish, staging/main updates,
state/configuration/authentication checks and verified temporary-access cleanup.
Application/dependency/test code is identical across the series; only the workflow
measurement label and immutable build identity differ. Dependency caches are warm;
these are complete cached pipeline measurements, not cold-host or dependency-upgrade
benchmarks. All samples, including the slower third run, are retained.

Times below are seconds. Initial queue is separate; verified/complete start at
first build-job start and INCLUDE inter-job waits (3–4 seconds). Complete also
includes cleanup/artifact retention. Each rollout includes readiness/config/auth
verification, not just Azure API submission.

| Run | Initial queue | Build | Staging rollout | Main rollout | Verified main | Complete CI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 / [39911985003](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39911985003) | 5 | 93 | 39.46 | 42.93 | 286.26 | 300 |
| 2 / [39912581349](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39912581349) | 3 | 94 | 36.27 | 42.82 | 256.96 | 277 |
| 3 / [39913096753](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39913096753) | 3 | 104 | 55.10 | 53.14 | 314.27 | 327 |
| 4 / [39913746690](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39913746690) | 4 | 88 | 45.40 | 38.13 | 266.88 | 281 |
| 5 / [39914306153](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39914306153) | 4 | 93 | 42.74 | 35.50 | 241.85 | 254 |

Median verified-main time: **266.88 seconds (4m27s)**, below the five-minute target.
Median complete CI: **281 seconds (4m41s)**. All ten warm image rollouts were
**35.50–55.10 seconds**, below the two-minute target. Initial queue was 3–5 seconds.
These measurements do not attribute the entire old shared-S1 deployment difference
to containers: hardware, release method and validation scope differ.

Final image on BOTH pilot slots:
`proximaimagelibrary.azurecr.io/image-library@sha256:3a7a7c24a525de119c9c4808b61cba2881f4d62d62b31fa2d3f2fd5d22cddd31`
(commit `f7c58f099dddd162af6ab47615bf9ee9d801721a`, build `39914306153-1`).

Final direct checks:

- Real Edge sessions completed Microsoft sign-in callbacks on both hosts;
  both homepages show v2.0.0, six catalog categories totaling 280 records and
  populated recent thumbnails. Authenticated maintenance status on both:
  `active_work=0, draining=false, read_only=true`.
- Independent Kudu VFS hashes match runtime state: main `23417242…`, staging
  `c4ed3373…`. Each remains its original pre-swap/recovery identity. Runtime
  UID/GID remains 65532 and ingestion is off.
- Both ingress configurations contain only `pilot-operator` and `Deny all`,
  with default Deny; no temporary `pilot-ci-*` rules remain.
- Insights for this exact build contains 85 requests, 56 dependency events
  (42 Graph, eight Microsoft login, four SDK-monitor and two startup), zero
  dependency failures and zero exceptions at the observation snapshot. Four
  `/api/pending-count` polls received 401; subsequent real sign-in callbacks,
  catalog reads, authenticated badge/status requests and thumbnails succeeded.
  The auth-denial events are retained, not hidden or claimed as zero failures.
- `library.liveproxima.org` still reports v1.0.5 / `0ddfd05`; CNAME remains
  `pp-app-serv.azurewebsites.net`. Remote `main` remains `0ddfd05`. No public
  cutover, legacy-app shutdown, catalog mutation, backfill or write canary was performed by this pilot.

Pilot mode is now **hold** after the requested series, pending cutover preparation.
The five raw scan files' hashes were independently checked against their release
receipts. Full build/deploy artifacts are also downloaded under
`/tmp/image-library-pilot-evidence.3zow09/accepted-1` through `accepted-5`.
Exact running/rollback receipts are preserved in `pilot-evidence/release-receipts/`;
structured timing evidence is `pilot-evidence/2026-10-23-complete-release-timings.json`.

## Completed gates

- Signed pilot-branch commits only; exact-image scan/test/provenance gate passes.
- Build/deploy GitHub OIDC and repository-scoped ACR push/pull work. Temporary
  CI ingress rules are removed after each successful deployment.
- Actual Azure runtime UID/GID 65532; read-only and ingestion-off guards active.
- Real Microsoft sign-in, homepage v2.0.0, categories and thumbnails verified.
- Actual Insights request and dependency ingestion verified by commit/build.
  Observed Graph dependencies are GETs; no catalog write canary was run.
- Persistent sentinel from the runtime matches the independent Kudu VFS hash.
  It survived replacement from run `39904263261-1` to `39904604019-1`.
- Source/Oryx and container were compared on the SAME dedicated P2v3, same
  commit `8e460140d8f80ca2d02f0228c5cd10cb9f027fd4`, same authoritative data,
  one synchronous worker, real authentication and read-only mode.
- Restart passed in 41.35 seconds: fresh boot, unchanged persistent-state ID,
  UID/GID 65532, exact image and enforced authentication.
- Seeded the new app's main slot with an earlier tested digest in 32 seconds;
  its source-baseline persistent state survived the switch to containers.

## Failed swap result and approved adjustment

The forward swap completed at the platform level but **failed application
acceptance**: the persistent `/home` state moved with the slot content. This was
confirmed independently by BOTH runtime readiness and Kudu VFS hashes:

| Public pilot hostname | Before swap state ID prefix | After swap state ID prefix |
| --- | --- | --- |
| New app main | `23417242` | `c4ed3373` |
| New app staging | `c4ed3373` | `23417242` |

No files were lost, but production-local checkpoints, quota counters and staged
uploads must not be replaced by staging state during a normal release. Both
slots remained read-only. The failure report is retained. Reverse recovery
passed in 84.70 seconds against the ORIGINAL checkpoint: both images, both
persistent-state IDs, nonroot execution and authentication were restored.
This recovery is not treated as a pass of the forward-swap acceptance gate.

**User-approved plan adjustment, 2026-10-22:** keep staging validation,
then update the new main app to the same tested immutable digest in place.
Keep its own `/home` state and credentials, accept a bounded restart, and restore
the previous approved digest once if post-deploy verification fails. This uses
the existing approved resources and matches the user's downtime tolerance.
It still needs a new five-run complete-release measurement and recovery gates.

Alternative: externalize local state to separately managed, slot-sticky storage
before retaining swaps. That adds infrastructure, access configuration and
migration work not included in the current approved resource set.

The measured series used `IMAGE_LIBRARY_PILOT_MODE=run`; mode is now `hold`
after successful completion. Legacy production/DNS remain unchanged.

### In-place rehearsal progress

- First forward update preserved main state but stopped on an overly strict
  configuration comparison: Azure's `lastModifiedTime` changes on any update.
  No blind rollback was attempted. This failed report remains retained.
- The corrected comparison excludes only the image and its audit modification
  timestamp; it still compares every setting/credential and other container
  properties in memory. No secret values or hashes are logged.
- Restoring the prior approved digest in place passed on both slots: staging
  33.69 seconds; new main 54.22 seconds. Each retained its original state ID,
  nonroot identity, authenticated boundary and unchanged configuration.
- CLI version behavior is accounted for: reassert the verified 8080 port when
  updating the image. Reject startup/environment/volume overrides before update.
- All 251 tests pass locally and in target-Linux CI `39909715224`; exact-image
  smoke, SBOM and the unchanged security gate also pass.
- Failed-start/readiness rejection and one bounded recovery passed in 100.57
  seconds, including unchanged main and restored staging state/auth. Azure
  independently reported the intentionally invalid startup exited with code 1.
- Failed-pull rejection and recovery passed in 83.84 seconds. Azure reported
  `ImagePullFailure` for the intentionally nonexistent digest; exactly one
  recovery restored the approved image and original state, with main unchanged.
- Actual automatic main rollback PASSED. After a real healthy candidate update,
  an explicitly recorded post-readiness gate fault exercised the release helper's
  recovery path: exactly one restoration of the previous approved digest in
  41.96 seconds, with original state and protected configuration unchanged.
  The candidate was NOT accepted as a successful release. This is distinct from
  the actual invalid-start and missing-image failure tests above.
- Five-run complete-release timing subsequently passed; see final acceptance above.

First complete CI release `39910716638-1` passed: 245.39 seconds from the first
build job starting to verified main, 256 seconds through complete CI cleanup;
initial queue 4 seconds. Staging/main rollouts were 31.04/39.08 seconds, with
both temporary access rules removed and both state/configuration checks passed.
This is preliminary, not the five-run acceptance statistic. A repeat-build cache
review found pytest could itself be cached. The pipeline now disables cache for
the disposable test stage only, keeping dependency caches; five comparable runs
will be measured with fresh test execution on every attempt.

Repeat `39910716638-2` failed closed BEFORE any image update: the earlier run
attempt's artifacts were no longer available after rerunning the workflow.
Both CI access rules were removed and both images/states remained unchanged.
The already-downloaded passing receipt from attempt 1 was preserved verbatim
in `pilot-evidence/release-receipts/39910716638-1.json` and cross-checked against
the original successful build-job security/publish logs. The helper may use only
such a reviewed exact unexpired checkpoint if artifact retrieval fails; missing,
expired or mismatched evidence still blocks. The first preliminary run's full
raw build artifact is no longer available; its prior 90-day retention statement
does not override this observed rerun behavior.

Use FRESH workflow runs, not reruns, for the five final measurements. Workflow
measurement-label-only commits will hold application code constant, with fresh
tests, exact-image smoke and scans every time. Preserve all build/deploy artifacts
locally as well as the 90-day GitHub retention for these accepted runs. This
measures the cached release pipeline, not dependency-upgrade or cold-host time.

## Comparable read experiment

One warm-up then 20 interleaved, sequential authenticated `/api/images` requests
per mode in Edge. Query labels prevent browser response reuse; application cache
was warm. Every response matched the same complete 280-record JSON fixture
exactly. No production data was modified and no parallel load was applied.
Browser times include navigation/automation and JSON-read overhead; these are
not pure server response times or a usable-grid measurement.

| Same P2v3 mode | Median | Nearest-rank p95 | Maximum |
| --- | ---: | ---: | ---: |
| Source/Oryx | 128.5 ms | 193 ms | 679 ms |
| Container | 124.5 ms | 193 ms | 627 ms |

Sorted source samples (ms): 116,118,120,121,122,123,124,124,125,128,129,134,146,148,152,155,167,188,193,679.
Sorted container samples (ms): 105,116,117,119,120,120,121,121,123,124,125,136,150,157,176,177,177,187,193,627.

Insights confirms requests for both modes at the same commit. Including browser
warm-up/homepage reads: source 23 requests, server p50 3 ms / p95 5 ms / max
886 ms; container 22 requests, p50 3 ms / p95 4 ms / max 473 ms; zero failures
in either set. Maxima include cache population, unlike the isolated warm sample.

Conclusion: no material warm-read regression. Packaging alone did not create
a large request-speed improvement. Dedicated compute and later concurrency,
pooling/caching and thumbnail work must be assessed separately.

## Deployment observations (not five-run release acceptance yet)

| Evidence | Measurement |
| --- | --- |
| Pilot `39903706929`, first actual container deployment | 27.93 s helper elapsed including preflight; cold-pull timing not isolated |
| Pilot `39904263261` | 25.76 s digest update through verified readiness/config/auth |
| Pilot `39904604019` | 36.80 s digest update through verified readiness/config/auth |
| Source baseline `39904604111`, same P2v3 | 44.82 s ZIP deployment through exact readiness; 111.01 s including configuration preflight |

The source baseline workflow does NOT run the container's full tests/scan, so
its total workflow duration is not a like-for-like CI comparison. Likewise,
the old shared-S1 17m20s release is not evidence that containers alone save that
time. Queue time, build time, image update and swap must remain separate.

## Gates remaining for public cutover (not part of the completed pilot)

- Validate protected state transfer, DNS/TLS/Entra custom-domain routing and rollback.
- Complete the supervised cutover gates before enabling writes or ingest ownership.
  No old-app shutdown, DNS cutover, asset deletion/backfill or write canary is included here.

Sanitized restart, seed, failed-swap and recovery receipts are checked into
`pilot-evidence/2026-10-22-*.json`. Full local downloaded evidence remains in
`/tmp/image-library-pilot-evidence.3zow09/`.
The five accepted fresh-run artifacts have 90-day retention and local copies.
The preliminary rerun artifact exception is explicitly documented above.

## Unattended pilot release procedure

- Only `perf/container-pilot` may use the build/pilot OIDC environments. Set
  `IMAGE_LIBRARY_PILOT_MODE=run` to allow new pilot builds, `hold` to prevent
  new ones. Holding does not cancel a release already in progress.
- The shared `image-library-deploy` concurrency group serializes deployment.
  A release downloads its exact passing build receipt and the currently running
  prior receipts; expired/missing/mismatched evidence stops before image update.
- Update staging, verify exact build/digest/state/auth/configuration, then
  update main to that SAME digest. Never swap or copy settings. Preserve the
  before/after report and actual verified timestamp in the CI artifact.
- An acknowledged update followed by a failed gate permits exactly one
  restoration of the verified prior digest. Recovery must preserve the original
  state and configuration. A recovered failed candidate still fails the release.
- Ambiguous Azure results, failed recovery or failed access cleanup stop further
  mutations. Put new runs on hold, inspect the run/checkpoint, Azure configured
  digest and live readiness on BOTH hostnames. Reconcile temporary `pilot-ci-*`
  rules to the exact finished run before removal; never remove the operator rule.
- Never replay an existing checkpoint or rerun a deployed workflow: reruns can
  invalidate earlier artifact availability. After reconciliation, use a fresh
  workflow run/report and preserve receipts for both running/rollback images.
  Keep the Actions job visible in Edge during supervision.
- This procedure covers the read-only isolated pilot only. Public cutover,
  writable production promotion, scheduled catalog work and cleanup remain
  governed by their separate gates and approvals.

## Maintenance observations retained for the next reviewed batch

- Review-badge polling continues every 30 seconds, including hidden/expired
  sessions. Pause on hidden tabs and 401 responses, and refresh after sign-in;
  this reduces redundant requests and auth-denial alert noise without bypassing auth.
- Before writable production cutover, add an explicit allowlisted slot label
  to telemetry. Current service/build attribution works, but both pilot slots
  share the role/build identity and the request-host aggregation returned empty.
  Do not infer per-slot error rates from the combined final-build counts above.
- Commits contain SSH signatures and signing remains enabled. GitHub currently
  reports `unknown_key` for the signing key, so these are NOT GitHub-verified
  signatures. Registering/trusting that key is a user-owned account follow-up;
  no account key or access configuration was changed during this pilot.
- CI warns that the pinned upload-artifact, azure/login and setup-buildx Actions
  target deprecated Node 20 and are being run under Node 24 by the runner.
  Refresh those reviewed SHA pins to native supported-runtime releases in a
  separate dependency batch, with full CI validation. No warning was suppressed.
- The reviewed CVE applicability policy expires on 2026-11-21 at 23:59:59 UTC.
  Rebuild/rescan and review before expiry; do not automatically extend it.
