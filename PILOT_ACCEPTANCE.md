# Container pilot acceptance evidence

As of 2026-10-22 PDT. **In-place promotion approved; validation in progress, not passed.**
Legacy `library.liveproxima.org` remains v1.0.5 / `0ddfd05`; DNS is unchanged.

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

Automatic pilot deployments are being resumed with `IMAGE_LIBRARY_PILOT_MODE=run`
after local validation and recovery rehearsals of the approved implementation.
Legacy production/DNS remain unchanged.

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
- Five-run complete-release timing remains pending.

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

## Remaining gates

- At least five comparable complete cached releases including promotion, with
  queue time separate; median target <=5 minutes, update/promotion targets <=2 minutes.
- Final consolidated evidence and explicit acceptance decision. No old-app
  shutdown, DNS cutover, asset deletion/backfill or write canary is included.

Sanitized restart, seed, failed-swap and recovery receipts are checked into
`pilot-evidence/2026-10-22-*.json`. Full local downloaded evidence remains in
`/tmp/image-library-pilot-evidence.3zow09/`.
Authoritative CI artifacts are retained for 90 days on each cited GitHub run.

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
- Never replay an existing checkpoint. Only after reconciliation, use a fresh
  run attempt/report. Keep the Actions job visible in Edge during supervision.
- This procedure covers the read-only isolated pilot only. Public cutover,
  writable production promotion, scheduled catalog work and cleanup remain
  governed by their separate gates and approvals.
