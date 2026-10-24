# New candidate rehearsal and staging validation

Authorized scope, October 24, 2026 UTC: review and publish a new immutable
candidate, exercise the isolated synthetic rehearsal, then deploy that same
digest to read-only staging and validate actual authenticated reads. Production
image/settings, production write-resume enablement, ingestion and schedules are
unchanged. Private unattended networking remains deferred.

## Reviewed source

- Stopped image changes and nonce-owned cleanup now require named old-container
  termination, protected state/configuration checks and one fresh runtime.
- Post-cleanup resume uses fresh-boot binding and protocol 2 durable request
  retirement. Ambiguous outcomes retain the lease and prohibit mutation replay.
- The defined local failure matrix is in `RELEASE_FAILURE_MATRIX.md`.
- Scoped four-file security review completed with no reportable findings. It
  does not prove effective cloud permissions or live Azure behavior.
- Rehearsal additionally exercises candidate stopped cleanup/restart, stale-boot
  rejection and exact one-shot resume with empty-channel readback. Its physical
  target remains only the synthetic rehearsal app. It does not claim full
  production-controller end-to-end or production-provider writable acceptance.

## Validation sequence

Read-only preflight caught historical staging image-pull failures that Azure
logs as unnamed zero-millisecond terminations. The lifecycle parser now accepts
only that explicit failed-pull sequence without retiring any named runtime;
unmatched or overlapping termination remains a failure. Regression tests cover
that distinction. No log truncation/deletion or safety bypass was used.

1. Signed source review/CI and main integration; no automatic deployment.
2. One fresh manual builder; authenticate receipt/digest and disable builder.
3. Pin the new candidate in the rehearsal harness, review/test it, run isolated
   rehearsal with bounded temporary single-runner access, verify rollback,
   stopped app, absent owned files, unlocked lease and removal of temporary rules.
4. Reverify current production/staging identities, containment and read-only
   staging configuration. Hold the release lease for a bounded staging-only
   cold deployment; preserve configuration/state and prohibit production writes.
5. Validate exact staging identity, authentication, catalog/thumbnail reads and
   matched baseline/candidate measurements. Record limitations honestly; health
   alone is not performance acceptance. Production promotion remains separate.

## Published candidate

PR #9 merged as `6c79415deb4b95f9aed60b52370e072fe54124ed`; its tree exactly
matches reviewed head `9587fe755f4f2e8ff9c467d1a15af6f444149090`. Container and
T1/dependency CI passed, including **1098 tests** and **15 JavaScript checks**.
The parser fix was independently checked against real staging lifecycle logs.

Fresh build [40070894451-1](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/40070894451)
passed in **2m02s** and published the same source, with fresh target tests,
smoke, dependency audit, SBOM and unchanged image-security gate. This is build
duration, not Azure deployment time. Builder enablement was returned to false.

- Image: `proximaimagelibrary.azurecr.io/image-library@sha256:d8b9d87eef6e2b4e1a82573762877371b6d63dc3db1edb6a3ae7e676c89f6ac1`
- Artifact: `12551506526`
- ZIP SHA-256: `35e184314b249eae880ad9d1a370a45b528a81f7b61473901573af37759ce043`
- Authenticated verifier checked exact run/attempt/head, pinned builder source,
  artifact integrity and digest-bound scan/smoke/SBOM evidence.

The rehearsal/staging harness pins this exact artifact; changing that pointer
does not rebuild or relabel the candidate. Rehearsal and staging outcomes follow.
The image scan retained eight individually reviewed vendor/backport/component-
absent findings, with zero unreviewed high/critical findings; this is not a
claim of zero reported CVEs.
GitHub emitted a non-failing Node 20 metadata deprecation for the pinned Buildx
action (runner forced Node 24); track its vendor update separately from this
immutable candidate, without weakening or silently replacing builder provenance.

## Rehearsal and staging checkpoint

PR #10 merged the exact candidate pin as `d0cb46a`. Isolated recovery run
`40071226303-1` passed in 6m24s, including the new stopped cleanup/restart and
protocol-2 stale/exact resume checks, synthetic rollback and cleanup. Verified
artifact `12551592242`, ZIP SHA-256
`b7e5ef5f519667638828e12e3b4455215e34ecf248812aaa3bec36c451874fe4`.
Independent operator reads confirmed prior image, Stopped, zero active runtimes,
absent owned files and unlocked lease. Temporary runner `57.151.87.21` / rule
`rehearsal-ci-40071226303` was removed from app/SCM/storage and operator-only
default-deny access verified. Both enablement flags are false. The protected
synthetic records remain under `ci-rehearsal/2f57089d3dec4c4fbc66a37e906f0b5d/`.

The first staging forward operation paused at strict cold readiness, retaining
the lease without replay or rollback. Subsequent direct reads found the exact
candidate ready, anonymous home redirected to login, maintenance returned 401,
and control files were absent. PR #11 adapted staging-only polling for the
Azure startup window: bounded 403/502/503 GETs are not acceptance; exact ready
identity and subsequent authenticated runtime/auth checks remain required.
Production adapter policy is unchanged. Reviewed head `0f0f766` passed both CI
checks before merge `183a460`; this is operator-tooling source, not a rebuilt
runtime image.

### Supervised staging reconciliation: passed

The original paused operation was reconciled explicitly, not retried. The
same private owner and lease, original backup, known mount, unchanged staging
state/configuration and actual named lifecycle were verified before proceeding.
No initial start was replayed and no replacement lease was acquired or broken.
Fresh exact identity, anonymous authentication boundaries and authenticated
protocol-2 runtime checks passed. A non-overwriting protected reconciliation
record was captured before the controlled prior-image rollback and final
candidate deployment. Both subsequent cold transitions passed with fresh named
runtimes, exact identity, unchanged protected state/configuration/mount,
read-only mode and an empty RPC channel. The lease was released and independently
verified unlocked. Private backup/reconciliation records remain under
`rollback-backups/712bd5476b834480883c04106a863e3b/`.

This is a successful **supervised reconciliation**, not a claim that the first
staging execution completed unattended. No state restore or production mutation
occurred. Live image updates returned HTTP 200; asynchronous ARM receipts remain
covered locally, not exercised by these live transitions.

## Browser and performance comparison

Authenticated Edge reads returned exactly the same 280 catalog records before
and after the staging image change. All 20 recent thumbnails loaded; three
sample thumbnail routes reached decoded 176x117 images at the final Microsoft
media host. Image-info and variations responses matched the baseline exactly.
Existing-session authentication continuity passed; a new interactive SSO flow,
upload, writable canary and representative usable-grid timing were not tested.

Browser navigation/response-read elapsed milliseconds, including browser and
automation overhead (not server-only timings). p95 uses nearest rank. These
small serial samples do not establish statistical significance or causality.

| Same staging slot, before/after | Prior median / p95 | Candidate median / p95 | Samples per build |
| --- | ---: | ---: | ---: |
| Warm catalog | 165 / 187 | 184 / 247 | 20 |
| Image info | 292.5 / 505 | 323 / 474 | 10 |
| Variations, including first read | 491.5 / 1855 | 618 / 1697 | 10 |

An additional interleaved check alternated production (unchanged prior image)
and staging (candidate), ten reads each per route, with exactly equal payloads:

| Paired current hosts | Production median / p95 | Staging median / p95 |
| --- | ---: | ---: |
| Catalog | 140 / 418 | 168 / 189 |
| Variations | 510 / 2136 | 562 / 1809 |

First-read/provider-cache effects may explain some tail variability but do not
establish the cause of slower medians. Hosts have different process/cache state.
The original before/after variations p95 after excluding each first sample was
542 ms prior versus 812 ms candidate. No overall performance win is demonstrated.
Raw sanitized timing samples are in
`cutover-evidence/2026-10-24-candidate-validation.json`.

## Final disposition

**Recovery and read-only functional validation passed; performance acceptance
remains open and production promotion is on hold.** Final independent reads
confirmed production Running on `40019125172-1`, staging Running read-only on
`40070894451-1`, one named runtime and absent control files in each, both release
leases unlocked, rehearsal Stopped on the prior image, both builder/rehearsal
flags false and pilot mode hold. Production/staging runtime resume enablement
remains absent/default off; ingestion remains disabled. Temporary runner access
was removed and verified. Protected evidence is retained.

Next work is to profile variations/provider round trips and measure representative
grid and upload latency, then evaluate an optimized candidate against the same
baseline. Full production-controller end-to-end acceptance, separate supervised
writable acceptance, the complete telemetry observation period and stable
unattended networking are not established by this rehearsal. The latter remains
deferred. No production deployment or write-resumption authorization is implied.
