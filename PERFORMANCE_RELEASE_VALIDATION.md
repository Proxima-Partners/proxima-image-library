# Performance release validation

Checkpoint: October 23, 2026, 23:15 PDT / October 24, 06:15 UTC.

**Result: available pre-deployment checks pass, but production release remains
NO-GO. The performance candidate is not deployed or performance-accepted.**

This validation used local tests, authenticated release-artifact verification,
read-only Azure queries and normal authenticated production browser reads. No
production/staging image, configuration, access, catalog, ingestion or schedule
was changed. No write canary or new CI job was run. Private CI networking and
the paid runner remain deferred; this report does not authorize provisioning.

## Exact release identities

| Item | Commit | Build | Image digest |
| --- | --- | --- | --- |
| Current production and staging | `2ffc0ff18ad191d1ccc1c185b4ce848b9442de4b` | `40019125172-1` | `sha256:1a1d24ede2eb7bfd81cb1ea2b11ea5518f0df5c4441dd714f2ef49ab5e1afa9a` |
| Published performance candidate | `ba61c526f522349ad6bfdbbd39d76448078bb91d` | `40064558508-1` | `sha256:f5ad233782189bf29457b52ee1394a04f0209640cf8672fc68c42690524f9c12` |

Repository: `proximaimagelibrary.azurecr.io/image-library`.
Local source HEAD: `c4dd5d9dfb6b6bc2ed60bda1422ab05246b7f2be`.
The candidate and HEAD have no differences in `src`, `static`, `templates`,
`requirements.txt` or `Dockerfile`; later release-tooling/documentation changes
mean their complete source trees and images are not identical.

## Fresh technical checks

| Check | Result | Boundary |
| --- | --- | --- |
| Pinned Linux/amd64 container tests | **693 passed**, 10 existing UTC deprecation warnings; 17.68 seconds | Fresh test stage; no network during pytest |
| JavaScript tests | **15 passed** | Local browser/workflow unit checks, not live candidate UI acceptance |
| Workflow actionlint | Passed | Static workflow validation |
| Strict Python dependency audit | No known vulnerabilities found | Not a fresh OS/container-image scan |
| Candidate artifact verification | Passed, artifact `12549051390` | Authenticated run/head/workflow, ZIP digest and image-bound scan/smoke/SBOM evidence |
| Prior artifact verification | Passed, artifact `12529602290` | Verified rollback provenance, not a new rollback rehearsal |
| Whitespace/diff checks | Passed | Existing user-approved deferral edits preserved |

Candidate artifact ZIP SHA-256:
`a4845461da5d0ba18d35afb2cf6800ab95a9ff389a553c87a90cc5b4e16ad8e4`.
Prior artifact ZIP SHA-256:
`41ca5f92a9d63e9bb36fcebd8cc76df480f17e13b46350c2062273058409a67b`.

The candidate build job ran from 05:00:35 to 05:02:43 UTC on October 24
(**2m08s**). This is build-job duration, not end-to-end deployment duration or
proof of a deployment-time improvement.

An operator-side pull of the exact private images failed authentication. Azure
returned an exposed registry token, but an isolated Docker login still failed;
the underlying refusal was not classified. No token was printed, no role or
network rule was changed, and the temporary credential directory was cleaned.
No fresh independent scan of the exact candidate image was therefore performed.
The authenticated CI scan evidence above remains distinct from a fresh scan.

## Live baseline: current production, not the candidate

Fresh ARM reads found production and staging Running on the prior digest above,
on dedicated `asp-image-library-p2v3`, P2v3, capacity 1. Both have Always On and
`/readyz`; production is writable, staging read-only, ingestion disabled, and
per-slot telemetry enabled. Resource Health reported Available. Production
release-resume enablement is absent/default-off. No settings values containing
credentials were exported into this report.

At approximately 06:04 UTC, public health/readiness/version returned 200 and the
anonymous maintenance endpoint returned 401. Version identity matched the prior
build. An authenticated Microsoft Edge session then displayed all 280 catalog
records and loaded all 20 recent-image thumbnails.

Twenty sequential warmed `/api/images` browser navigations each returned 280
records. Unique validation query values avoided browser response reuse. Timings
include browser automation and JSON processing, not just network/server time:

| Measurement | Sample | Median | p95 | Maximum |
| --- | --- | --- | --- | --- |
| Warm authenticated browser catalog navigation | 20 requests | 149.5 ms | 189 ms | 192 ms |
| Server telemetry for `/api/images`, 06:07–06:10 UTC | 22 requests, 0 failures | 3 ms | 4 ms | 4 ms |

The server sample includes nearby reads and is not a request-ID-matched copy of
the 20 browser measurements. Neither measurement is grid-usable time. Record
counts, not full catalog-field equivalence, were checked during these probes.
The 20 browser samples in milliseconds were:
`131, 169, 189, 132, 167, 137, 139, 136, 122, 172, 156, 192, 143, 125, 182, 127, 174, 175, 165, 140`.

### Observation window and resource use

Queries were restricted to telemetry role `image-library-container` and instance
`production:40019125172-1`, over **21:08 UTC October 23 to 06:04 UTC October 24**
(8h56m). This is not the required 24-hour observation.

- 371 request events; no 5xx. Of 123 failed requests, 114 were unmatched 404s
  whose causes were not investigated, and 9 were maintenance-endpoint 401s.
- Actual usage was sparse: one image-info read (304 ms), one variations read
  (2,242 ms), two tag reads, and no catalog API reads in this pre-probe window.
- 91 thumbnail redirects had p95 501 ms. This measures redirect responses,
  **not final thumbnail bytes or rendering**.
- 97 Graph GET dependencies returned 200: p50 266 ms, p95 653 ms, max 924 ms.
  No exception events were returned for the scoped window; telemetry absence
  does not prove every application/background path was exercised.
- Dedicated-plan hourly average CPU was 1.52–2.14% (maximum 8%); average memory
  17.03–18.25% (maximum 20%). These plan-wide figures include the dedicated
  slots/rehearsal, not only production. They show no observed saturation during
  this sparse window, not capacity under representative demand.

The minimum observation cannot close before **October 24, 14:08 PDT** and needs
real telemetry review, not just elapsed time. The generic diagnostic collector's
deployment-history command is unsupported by this installed CLI; current image
and configuration identity were verified through direct read-only ARM calls.

## Offline cache-mechanism comparison

A network-disabled, read-only Linux test container exercised the real catalog
route using 280 synthetic records and a fake provider with 50 ms artificial
latency. The prior build's actual `get_all_records` function was compared with
the current/candidate implementation; other route code was shared. Each mode
had one cold read and 200 warm reads, with matching fixture responses. Five
concurrent cold callers separately exercised the cache function directly.

| Metric | Prior cache function | Candidate cache function |
| --- | --- | --- |
| Warm fixture-response median | 1.303 ms | 2.403 ms |
| Warm fixture-response p95 | 1.491 ms | 2.528 ms |
| Provider reads for cold + 200 warm requests | 1 | 1 |
| Provider reads for five concurrent cold function callers | 5 | 1 |

The candidate coordinates duplicate refreshes successfully and adds about 1 ms
to warmed fixture responses for defensive data copying. This is **not a measured
production speed improvement**. Cold timings are dominated by synthetic delay.
The app still uses one synchronous Gunicorn worker; direct cache concurrency
does not establish concurrent HTTP throughput or nonblocking uploads.

## Open gates and next sequence

1. **Production deployment safety:** `AzureProductionAdapter.update()` still
   updates `sitecontainers/main` directly, without the verified stop/zero-old-
   runtime/start lifecycle enforced in the isolated rehearsal. The production
   verify/cleanup path and full failure matrix also need that lifecycle policy.
   Passing the rehearsal does not prove the actual production controller safe.
   Implement and test that separately before a production release; retain
   fail-closed lease handling and no blind mutation retries.
2. **Supervised access and containment:** verify the intended operator/release
   identity path, restrictive access, non-cooperating writer containment and
   protected rollback state. Resolve registry pull capability without assuming
   new permissions. Private CI networking is deferred, not a prerequisite to
   appropriately scoped supervised validation.
3. **Candidate staging acceptance:** deploy the verified immutable candidate to
   read-only staging only under the applicable release authorization. Validate
   actual candidate boot, identity, sign-in, catalog equivalence, final thumbnail
   bytes and controlled rollback. If runtime code changes, publish and verify a
   new candidate instead of relabeling this digest.
4. **Measured performance acceptance:** compare baseline and candidate using
   identical sample sizes, cache states, request types and controlled host/region
   conditions. Measure image/variations reads, thumbnail delivery and usable-grid
   time, not only health or redirects. Warm read p95 below 500 ms and usable grid
   below 1.5 s remain targets, not general results proved here. Investigate the
   observed slow variations path and 404s. Any new disposable upload test and its
   cleanup need explicit scoped approval; the prior canary approval is consumed.
5. **Observation and supervised release:** finish the real 24-hour review and
   obtain the separately required supervised production release/writable
   acceptance approval. Promote the same staging-accepted digest in place,
   with the protected rollback gates; do not use a slot swap. Measure complete
   deployment duration separately from build duration.

The current warm catalog baseline is already fast. Expected benefits from
refresh coordination, connection reuse and reduced polling must be measured in
the workloads they affect; they do not yet establish that the user's overall
slowness is resolved. No tier increase is justified by this limited baseline
alone. Reconsider private unattended infrastructure after performance acceptance,
with separate approval for provisioning and activation.

See `PRODUCTION_READINESS.md`, `PRODUCTION_RELEASE_RUNBOOK.md` and
`OPERATIONS_ACTIVATION.md` for the governing release and activation boundaries.
