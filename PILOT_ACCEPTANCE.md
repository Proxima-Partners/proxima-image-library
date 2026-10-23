# Container pilot acceptance evidence

As of 2026-10-22 PDT. **In progress, not a production cutover.**
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

- Restart persistence and fresh-boot proof.
- Seed new-app main slot with a tested container while retaining its source
  baseline state; forward/reverse swap and auth/state/identity checks.
- Failed-readiness and failed-pull rejection and one bounded recovery each.
- At least five comparable complete cached releases including promotion, with
  queue time separate; median target <=5 minutes, update/swap targets <=2 minutes.
- Final consolidated evidence and explicit acceptance decision. No old-app
  shutdown, DNS cutover, asset deletion/backfill or write canary is included.

Local downloaded evidence: `/tmp/image-library-pilot-evidence.3zow09/`.
Authoritative CI artifacts are retained for 90 days on each cited GitHub run.
