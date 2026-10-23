# Image Library container implementation plan

Date: 2026-10-22 (America/Los_Angeles). Status: approved; implementation in progress on the pilot branch. See `upgrade-status.md` for execution evidence.
Baseline commit: `0ddfd050160f5363a1ebb87ade588509b7a426e0`.

**Approved adjustment, 2026-10-22:** the actual forward swap failed the state-
ownership gate and reverse recovery restored both slots. The user approved
staging validation followed by updating the SAME tested digest in place on the
new main app, with a brief restart and at most one verified rollback. No more
slot swaps are used for releases. Preserve every main-slot setting/credential
and its `/home` state; never copy staging configuration. Ambiguous Azure results
require reconciliation, not another mutation. This supersedes swap-specific
steps below; the failed swap remains recorded, not reclassified as a pass.

## 1. Decision and scope

Build the application image in GitHub Actions and run it on Azure App Service for Linux. Use a new, dedicated P2v3 plan with one instance and a new Image Library app with a staging slot. Store images in a private Azure Container Registry (ACR) in West US 2. Keep SharePoint as the authoritative asset/catalog store and retain Application Insights.

The user prioritizes speed over cost, is currently the only user, and permits production downtime if necessary. Therefore use a controlled maintenance cutover, not weighted traffic splitting, multi-region infrastructure, Kubernetes, or a zero-downtime data migration. Keep the existing app and its settings recoverable. No production interruption is needed during image development or the pilot.

Containers do not inherently require a new app or a DNS change. Converting the existing app on S1 would avoid that cutover, but would leave the shared-compute bottleneck in place. The new-app route is recommended here to obtain dedicated compute without relying on the unresolved legacy-webspace move.

This document authorizes nothing by itself. Implementation, new resources/access assignments, and the exact DNS/TLS cutover require approval of the implementation scope. Downtime permission is already recorded; no deletion, backfill, catalog migration, or arbitrary access change is implied.

## 2. Current evidence and blockers

| Finding | Consequence for the design |
| --- | --- |
| `PP-App-Serv` and its staging slot run Python 3.12 on shared `proxima-plan-s1`; `PP-MCP-Server` also uses that plan | Do not resize, delete, or repurpose the shared plan; isolate Image Library on new compute |
| The app reports webspace `proxima-connector-rg-WestUS2webspace-Linux`; the original resource group no longer exists | A new plan in `PP-Resources` cannot be assumed compatible with an in-place move; use a new app instead of forcing the move |
| No ACR was returned by the subscription inventory | Registry and narrow push/pull permissions must be provisioned |
| Latest completed release took 17m20s; staging source deploy 10m18s, readiness gate 2m09s, swap 3m59s | Move builds off the serving plan; separately measure image pull/start and swap time |
| `startup.sh` runs one synchronous Gunicorn worker | Container packaging alone will not remove request serialization |
| Both production and staging have `SHAREPOINT_INGEST_FOLDER=Images/Ingrest-images`, and importing `src.app` starts the poller | Treat duplicate processing as a risk, not a proven incident; disable background writers in every nonproduction app before rollout |
| The poller can upload records/files and delete ingest sources; its lock is process-local | Never run overlapping old/new/staging pollers; do not enable scale-out or multiple worker processes |
| `/home` holds staged uploads, maintenance state/checkpoints, provider keys and quota counters | Explicit persistent storage and a verified state-transfer/rollback procedure are required |
| `library.liveproxima.org` is a CNAME to `pp-app-serv.azurewebsites.net`, observed TTL 3600 seconds | A replacement app needs a deliberate DNS/TLS cutover; DNS rollback is not instantaneous |
| The existing release workflow deploys every push to `main` | Pilot commits must not accidentally deploy to production; introduce explicit release-mode/target guards first |

The timing evidence is [Actions run 39888746988](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39888746988). Azure confirms that changing a resource group's name/location metadata does not move a plan between webspaces. [Plan-move rules](https://learn.microsoft.com/en-us/azure/app-service/app-service-plan-manage).

## 3. Target architecture

```text
Trusted GitHub commit
  -> Linux/amd64 image build + tests + dependency/OS scan
  -> ACR: immutable release digest + build evidence
  -> new Image Library staging slot: checks, no background writes
  -> gated promotion of the same digest
  -> new Image Library production slot
       -> SharePoint (existing authoritative data)
       -> persistent app state (/home)
       -> Application Insights (separate app/slot identity)

Existing PP-App-Serv: preserved rollback target during acceptance
PP-MCP-Server and other applications: unchanged
```

Proposed resources, all subject to name availability, policy, quota and approval:

- Subscription: existing `PP-Azure-Subscription` (`9528fb58-4fa4-43f8-9940-e5c3e1f1903f`).
- Resource group/region: `PP-Resources`, West US 2. If new P2v3 allocation is rejected, stop and present the exact alternative; do not silently select another region or group.
- Compute: dedicated Linux P2v3, one instance, Always On; candidate plan name `asp-image-library-p2v3`.
- App: candidate `pp-image-library`, with one `staging` slot. Confirm the final generated default hostnames rather than constructing them from names.
- Registry: dedicated private ACR Premium, same region. Premium is a speed-first choice for greater image throughput; it is not a claim that this small application's pulls need its full capacity. No geo-replication or private-network redesign in the first release. [ACR tiers](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-skus).
- Container configuration: one main container using App Service `sitecontainers`; no extra sidecars. Set explicit `targetPort=8080` and matching `PORT=8080`. Do not mix classic `WEBSITES_PORT` configuration into this mode. Rehearse in-place forward/reverse digest updates and storage behavior on the pilot. [Container configuration](https://learn.microsoft.com/en-us/azure/app-service/configure-sidecar).
- Keep one process initially. A dedicated P2v3 provides headroom but does not make process-local state safe across processes or instances.

## 4. Implementation work packages

### A. Containment and container image

Release action added by the user: update the homepage application version to `v2.0.0` through the shared `src.__version__` value. Assert the exact homepage badge and `/api/version` value in regression tests; verify the public homepage after cutover.

1. Add fail-closed controls for background ingestion, read-only pilot operation and maintenance/drain mode. Nonproduction ingestion must remain off, including during swap warm-up. Do not rely only on sticky settings: a swap can temporarily apply production settings to staging. Keep ingestion off throughout the first migration and explicitly designate its sole owner afterward.
2. Cover all mutation entry points, including GET/SSE maintenance and upload-processing routes. Blocking POST alone is insufficient. Read-only checks must never import a module that starts the poller or use a live write path as a smoke test.
3. Add a multi-stage Dockerfile and strict `.dockerignore`. **Base-image adjustment approved 2026-10-22:** use Docker's digest-pinned hardened Python 3.12.15 / Debian 13 runtime and matching dev builder for Linux/amd64, replacing the initial Debian-slim candidate. The runtime is shellless and uses the vendor's UID/GID 65532; retain the current Python 3.12 dependency baseline for the first parity measurement. This approval does not accept vulnerability exceptions or change the HIGH/CRITICAL release gate. Run a separate compatibility candidate for the latest supported Python (currently 3.15); promote that runtime only after wheel availability, full tests and application contracts pass. Do not hide a major runtime upgrade inside the initial packaging change. [Python lifecycle](https://devguide.python.org/versions/).
4. Cache dependency installation before copying frequently changing source. Keep tests/build tools out of the final runtime image. Keep code in `/app`, the virtual environment outside `/home`, and mutable state on explicit writable paths.
5. Use a fixed non-root runtime UID, provided the actual Azure-mounted state directories pass ownership/write/rename tests. Do not solve permission failures with blanket world-writable permissions.
6. Start Gunicorn through the exec-form Python entrypoint `scripts.container_start`, which validates `PORT` and replaces PID 1 with the single-worker Gunicorn master. Keep `startup.sh` unchanged for the legacy source deployment. Test signal handling, real maintenance child processes and bounded shutdown. No `pip install`, Oryx build, migrations, ingestion or catalog repair at startup.
7. Include `build_info.json` and revision labels. Exclude `.env`, `.git`, virtual environments, local catalog/test data, uploaded assets, key files and host logs from every image layer and build cache. Reuse the current release allowlist logic where practical.
8. Keep `/health` for local liveness and `/readyz` for initialized application state/exact commit. Add local state-directory and image-codec checks without making Graph or AI availability a platform restart trigger.

These choices follow [Docker image guidance](https://docs.docker.com/build/building/best-practices/). The first acceptance criterion is behavior parity, not an assumed speed gain.

### B. Build-once pipeline and permissions

1. Build on a fixed, supported Linux runner image. Validate and pin Actions to reviewed full commit SHAs; do not combine unrelated SDK upgrades with containerization.
2. Build one runtime image. Run the repository regression suite as the same non-root UID on the actual shellless runtime OS with networking disabled. Add test dependencies only to a discarded test stage, constrained by the production requirements. Then run black-box checks against the exact final image. Test native Pillow/WebP support, imports, authentication boundaries, readiness, SSE, restart persistence, CA trust, absent privileged utilities, immutable application code and PID-1 signal handling.
3. Scan resolved Python packages and OS packages; produce an SBOM and provenance/release manifest. Block newly introduced high/critical findings unless an explicitly reviewed, expiring exception exists. A scan failure or unavailable scanner is not a pass.
4. Use registry-backed BuildKit caching with separate trusted cache references. Untrusted pull requests get no Azure deployment credentials and cannot publish or poison the trusted release cache. [Build caching](https://docs.docker.com/build/ci/github-actions/cache/).
5. Use GitHub OIDC, scoped to the repository and approved branch/environment, for build/publish/deploy. Use managed identity for runtime pulls. Keep ACR admin credentials and anonymous pulls disabled. Separate the image publisher from production promotion permissions.
6. Prefer repository-scoped ABAC: Repository Writer for the publisher and Repository Reader for the app/slot pull identities, with explicit repository conditions. Include the cache repository only for the builder. These roles differ from legacy `AcrPush`/`AcrPull`; confirm registry permission mode and managed-identity pulls in the pilot. [ACR permissions](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-rbac-abac-repository-permissions).
7. Deploy by immutable `sha256` digest, not `latest` or a moving tag. Capture commit, base-image digest, release digest, test/scan reports, target resource IDs and timing. Promote the tested digest without rebuilding. Existing commit-only readiness is necessary but insufficient when two images use the same commit; also verify the configured digest and record a distinct build ID in telemetry.
8. Add a pilot-only dispatch path on an implementation branch. Retain the current source deployment as an explicit legacy rollback path; prevent both pipelines deploying from the same push. Before any implementation merge, establish target guards and document whether that merge triggers a live deploy.
9. Use one shared deployment concurrency lock, `cancel-in-progress: false`, bounded timeouts and resume-from-recorded-state behavior. No blind restart or re-swap after a timeout: reconcile GitHub, Azure and live identity first.

GitHub OIDC and container deployment are supported App Service patterns. [Microsoft workflow guidance](https://learn.microsoft.com/en-us/azure/app-service/deploy-container-github-action).

### C. Isolated Azure pilot

1. Provision only the approved resources and role assignments through narrowly scoped, repeatable infrastructure definitions. Keep live secrets out of source and outputs. Do not rotate or replace existing application credentials as an incidental step.
   New apps/slots have different system-assigned identities: existing identity permissions and Key Vault reference access do not automatically transfer. Inventory and grant only the required access; do not copy a principal ID or borrow Pete's identity as a shortcut.
2. Start with offline fixtures in CI. For Azure functional testing, use real authentication, disabled auth bypass, restricted pilot access and isolated test data. Production catalog access, if needed for read comparison, must be explicitly read-only with tested mutation guards and least-privilege credentials where available.
3. Add only the required pilot callback URI to the intended Entra registration, after approval; production keeps `https://library.liveproxima.org/auth/callback`. Check `APP_BASE_URL`, CORS, cookie behavior, MCP delivery URLs and direct-host clients. Do not publish pilot URLs into the real catalog.
4. Enable and verify `/home` persistence deliberately for the chosen container mode; do not infer persistence from directory existence or an image declaration. Keep pilot and production state separate. Keep all automatic ingestion off.
5. Keep privacy-filtered telemetry and a distinct app/slot role. Check actual ingestion, not just the `/readyz` initialization flag. Do not put credentials, asset content or donor/user identifiers into new build or diagnostic reports.
6. Exercise cold pull, cached update, restart, forward/reverse in-place digest updates, failed readiness, failed pull and recovery to an earlier digest. Confirm state and protected configuration remain with each hostname. A passing unexpired CI receipt must match the prior rollback image/build before any update.
7. To separate container benefits from hardware benefits, benchmark the same fixture workload on the same P2v3 size using source/Oryx and container deployment before finalizing the pilot. Report the old-S1 to new-P2 improvement separately; do not attribute all of it to containers.

### D. Controlled production cutover

Reserve a 60-minute maintenance window; aim for a 15–30 minute interruption after all preflight work passes. This is a planning target, not a guarantee: DNS caching, TLS issuance and state-transfer size can extend it. With one user, prioritize correctness and rollback over traffic-splitting infrastructure.

Before the window:

- Verify exact new app/plan/slot IDs, DNS provider access, custom-domain ownership, TLS issuance/binding procedure and Entra callback behavior. Do not remove the old binding until the new-host and rollback procedures are understood. [Domain migration](https://learn.microsoft.com/en-us/azure/app-service/manage-custom-dns-migrate-domain).
- Lower the relevant DNS TTL to 300 seconds if supported, then wait at least the previously observed 3600-second TTL before cutover. Do not assume this makes every resolver instant.
- Save a protected configuration inventory, previous DNS/TLS values, old source artifact and new/previous image digests. Do not print secret settings or place them in ordinary CI artifacts.
- Inventory `/home` by names, sizes and integrity hashes; identify only required application state. Do not copy the old Python environment, Oryx output or entire mounted home into the new app.
- Confirm there are no active upload/SSE/ingest/maintenance jobs. User previews held only in memory must be finished or explicitly abandoned; they cannot be restored from a file backup.

During the window:

1. Announce the interruption. Put the old app into a tested no-new-writes/drain state; disable automatic writers in old production, old staging, new staging and new production. Wait for active work to finish; do not kill an unknown in-flight write.
   The drain implementation must let a running poller/job finish before configuration changes that restart the process. If active-job state cannot be determined, stop the cutover and reconcile it; low user traffic is not proof of no background work.
2. Snapshot and transfer the specific persistent files below over an authenticated channel; verify hashes, permissions and directory writability. A dry-run file manifest must precede the copy. Keep the original copy intact.
3. Keep the new app read-only. Stop the old Image Library app/slot if necessary to guarantee a single writer; never stop the shared plan or Pete. Stopping occurs only after state export and rollback prerequisites are ready.
4. Apply the approved custom-domain/DNS/TLS change to the new app. Keep the same public URL and production callback. Check any integration that stored the old direct Azure hostname; a CNAME change does not update those clients automatically.
5. Verify TLS, sign-in, admin protection, catalog reads, visible thumbnails, MCP read delivery, exact commit/digest and telemetry at the real custom domain. User MFA, if required, remains a user-owned step.
   Disable `PILOT_STATE_PROBE_ENABLED` before enabling normal writes; this
   pilot-only check deliberately refuses startup unless the app is read-only
   and ingestion is disabled. Preserve its non-secret sentinel as test evidence.
6. Enable writes only after read/auth checks pass. Run at most the explicitly approved small canary (for example 1–3 named test assets); no automatic deletion afterward. Verify original/derivative files, rights, metadata and absence of duplicate records.
7. Keep automatic ingest disabled until a single active owner is verified. Record whether normal ingest was resumed or remains paused. Never silently create a second consumer of the production ingest folder.
8. Observe for 24 hours. Retain the old app, settings and artifacts for at least seven days; cleanup is a separate approval. The old shared S1 plan must remain because Pete uses it.

Required state handling:

| State | Treatment |
| --- | --- |
| `/home/proxima_staged_uploads/` | Drain first; preserve remaining files with a manifest; never auto-reprocess consumed uploads |
| `/home/proxima_maintenance_state.json` and `/home/proxima_maintenance_checkpoints/` | Preserve and verify; checkpoint existence is not permission to restore catalog data |
| `/home/proxima_ss_counter.json` | Preserve counts; do not reset paid-provider quotas |
| `/home/proxima_stock_keys.env` | Treat as a secret; restricted transfer, no logs/ordinary artifacts; preserve existing environment-variable precedence |
| Tag-library fallback | Set an explicit persistent path; do not rely on the macOS-oriented default path or an implicit container home |
| SharePoint assets and list | Stay authoritative and in place; no bulk copy, normalization or retagging |
| Preview tokens, rate-limit state and caches | Process-local; accept expiry/reset only after drain; no promise of session/job continuity |

## 5. Verification and release gates

Required correctness gates:

- Entire isolated `pytest tests -q` suite passes on target Linux/Python; prior 127-test result is a baseline, not a substitute for new tests.
- Final-image smoke tests, native image codec checks, non-root write/rename and restart persistence pass.
- Real authentication remains enforced; Azure `TEST_MODE` and `DEV_AUTH_BYPASS` must be false. No background or catalog writes occur from pilot/staging checks.
- Exact release digest/commit is traceable; `/readyz` passes and request/dependency telemetry arrives with the new build identity.
- Forward/reverse deployment rehearsals preserve state and the single-writer rule.
- There are no new unapproved high/critical vulnerabilities, catalog loss, missing required state, duplicate canary records or permission regressions.

Performance targets (measure, do not promise):

| Measurement | Initial target / procedure |
| --- | --- |
| Cached code-only release | Median at most 5 minutes from workflow start to verified production across at least five comparable runs; report queue time separately |
| Image rollout | At most 2 minutes from digest update to exact readiness on a warm host |
| In-place main promotion | At most 2 minutes on the dedicated plan; include restart/warm-up and verification, not just API submission |
| Cold deployment | Report full pull/start separately; do not discard slow uncached samples |
| Application reads | No material regression: compare identical authenticated route samples/cache state on identical compute; separately track thumbnails and Graph/AI waits |
| Subsequent app optimization | Work toward warm read p95 <500 ms and usable grid <1.5 s; these are not container acceptance promises |

Low traffic is not evidence that the app is fast. Use bounded fixture/synthetic reads, repeated browser checks and measured production traces; never load-test mutating endpoints. Unmet speed targets require investigation and a reported decision, not a claimed success.

## 6. Rollback

Two different rollback procedures are necessary:

1. **Normal container release:** before promotion, a failed staging gate leaves main unchanged. After an acknowledged update, reconcile the configured digest and unchanged protected configuration before restoring the already-tested prior digest in place. Verify the original state identity, exact build, authentication and settings. Allow at most one automated rollback; stop if recovery fails or a control-plane result is ambiguous. Do not oscillate between versions or swap slots.
2. **Initial old-app to new-app migration:** retain the old source app and protected state snapshot. If TLS/auth/readiness/state validation fails, keep writes disabled, restore the documented domain/DNS/TLS route and verify the old app before resuming writes. If the new app has already accepted writes, first reconcile its changed local state; never overwrite newer state with the old snapshot or reverse SharePoint changes automatically. DNS rollback can take time.

Use a cutover checkpoint after 20 minutes without a healthy authenticated target: begin the documented rollback rather than making open-ended production changes. Do not begin the outage at all without a workable certificate/domain rollback path. No data/schema migration is included in this release, which limits rollback complexity.

## 7. Unattended operating model

- Every approved release: tests, package/OS scans, build evidence, staging verification, serialized promotion and post-release checks; retain a durable run ID, digest and outcome. Keep the live GitHub Actions job visible in Edge during supervised deployments.
- Daily: scan deployed image digests for newly disclosed vulnerabilities and check readiness/error/latency trends. Failures produce an actionable report; they do not autonomously delete assets or change credentials.
- Weekly: propose dependency/base-image updates, rebuild, test and scan. Keep major runtime/SDK updates in their own reviewed batches. Retain deployed and rollback digests; image cleanup starts as a dry-run report, not automatic deletion.
- Read-only catalog maintenance: reuse `scripts/library_health_check.py`, but first remove duplicated diagnostic logic and add real pagination/page/record/time limits, sampled thumbnails, redacted machine-readable reports and an explicit incomplete flag. It currently loads the whole catalog and can download every thumbnail; do not schedule it unchanged. Run from the tested image on a separate GitHub runner initially, not inside the web process. Add scoped read credentials only after approval.
- Scheduled GitHub jobs are best-effort diagnostics, not a precise-time durable queue. Warn on missed runs and record progress; do not describe these as guaranteed execution.
- Writing jobs later: separate worker/queue, durable lease, idempotency key, checkpoints, cancellation and bounded retries. Automatic ingestion currently deletes source files, so moving it to a new job runner requires an explicit dataset/behavior review. No retry of a consumed upload, repair, deletion or backfill without its own scope.
- Fully unattended production promotion is enabled only after the pilot, rollback rehearsal and first supervised cutover establish the policy. Fail closed on missing permissions, expired credentials, incomplete evidence or ambiguous deployment state; request help for MFA or new access.

## 8. Proposed change sequence and deliverables

| Order | Deliverables | Exit gate |
| --- | --- | --- |
| 1 | Writer/drain/read-only controls, Dockerfile, `.dockerignore`, runtime/image tests | Local/CI parity; no live deployment |
| 2 | Build-only/pilot workflow, digest/build manifest, cache, SBOM/scans, narrow infrastructure definitions | Reviewed exact resource and permission diff; no production-target ambiguity |
| 3 | Approved dedicated P2v3, ACR, new app/slot and identity setup; pilot runs | State, auth, restart, in-place promotion/rollback and performance evidence |
| 4 | Approved DNS/TLS/config/state cutover runbook and execution | Verified real public host; user can browse and approved canary passes |
| 5 | Container-only normal release pipeline, monitoring and read-only maintenance schedule | 24-hour observation; documented rollback retained |
| Later | Threaded request handling, HTTP pooling/cache coalescing, derivative/background work, latest-runtime adoption | Separate tests and measurements; no automatic scale-out |

Likely implementation files: `Dockerfile`, `.dockerignore`, container-specific CI workflow, narrowly scoped infrastructure files, container smoke tests, readiness/build identity support, ingest/maintenance guards and release documentation. These are planned files/edits, not changes made by this document.

Approval should identify the exact new resources and roles, any Entra callback addition, the domain/TLS change and state-transfer scope, and any named canary assets. The user has already accepted necessary downtime. No application code, workflow, cloud resource or production state has been changed in this planning step; this plan is local and has not been pushed to the deployment-triggering branch.
