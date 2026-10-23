# Upgrade status

Updated: 2026-10-23 (America/Los_Angeles).

## Current execution checkpoint

**Fresh candidate and read-only Azure acceptance passed. Final cutover is next.**
Build `40019125172-1` / commit `2ffc0ff` passed 487 tests, exact-image security and
smoke gates, and both in-place deployments. Both real workers passed the Azure
filesystem probe. Production's read-only restart and stopped-SCM recovery passed;
file/directory no-overwrite transfer rehearsal also passed. Per-slot telemetry,
original MCP-secret compatibility, matching direct JPEG thumbnails, custom-SNI
TLS and authenticated staging v2.0.0/280-record UI are verified.

New main now has the preserved production provider/MCP settings, limits/CORS and
custom-domain callback, while both slots remain read-only with ingestion off.
Its SCM rules are independently operator-only; main app ingress is still restricted.
Legacy production remains live, old staging stopped, legacy workflow disabled,
pilot mode `hold`, and remote `main` unchanged. All completed preparation leases
are released. DNS still points to the old app; prior TTL expires at 20:55:10 UTC.
No final transfer, public cutover or write canary has happened. See
`cutover-evidence/2026-10-23-readonly-cutover-readiness.json` for exact gates.

### Azure-aware policy preparation (historical)

**Azure-aware state policy approved and being validated; public cutover remains
pending.** Fresh candidate `a15474c` / `40016044994-1` passed 459 target-Linux tests,
security/smoke gates and both read-only in-place deployments. Live staging's SCM
channel verified actual single-worker UID/GID 65532, zero active work and a bounded
catalog read. The new environment-only credentials/shared-mount policy requires
another fresh build; no real application state has been transferred.

Legacy deployment workflow is disabled; old staging is stopped
with a verified stopped-writer backup. Old production stays online at v1.0.5.
All four preliminary private configuration/state/source backups passed readback;
both legacy states passed isolated Linux recovery as UID/GID 65532. Separate
histories/quota were preserved, with no merge, reset or replay.

Only the library CNAME TTL changed (3600 -> 300); its old destination is intact.
All four authoritative DNS servers verified the change at 19:55:10 UTC; the old
cache window expires conservatively at 20:55:10 UTC / 13:55:10 PDT. Lease state must
be checked live; synthetic mount rehearsal retains its lock on any ambiguity.
No main commit/push, production stop, final state transfer, DNS destination change
or write canary has occurred.
See the current runbook and `cutover-evidence/2026-10-23-containment-and-backups.json`.

### Earlier TLS checkpoint (historical)

**Target TLS preparation PASSED; public production cutover remains NO-GO.**
The supplied private key matches the wildcard certificate. Chain/hostname/server-
auth checks passed; an encrypted PFX was imported from memory only. Certificate
`image-library-tls-99c1349350b3` is SNI-bound to `library.liveproxima.org` on the
new app. Five strict direct-target TLS/HTTP rounds verified v2.0.0, exact accepted
pilot build, readiness and anonymous auth boundaries. An initial TLS failure is
retained in the evidence; no certificate/binding mutation was repeated. The held
release lock was released only after reconciliation and is now unlocked.

Source key permissions are now 0600; original bytes remain in Downloads. DNS/TTL,
the old TLS binding and public v1.0.5 route remain unchanged. Both new slots remain
read-only with ingestion off and operator-only ingress. No app deployment,
commit/push, state transfer or canary occurred. TLS expires 2027-04-18; renewal
automation/alerts still need implementation. See
`cutover-evidence/2026-10-23-tls-preparation.json` and the runbook TLS checkpoint.

Remaining gates: trusted release artifacts and live adapter/recovery rehearsal,
legacy-writer containment, verified backup/restore/transfer, DNS TTL window,
fresh custom-domain SSO and the approved single disposable writable canary.

### Release-storage and control preparation checkpoint

**Dedicated release storage verified; production cutover remains NO-GO.**
User-approved `pilrelease9528` storage and two private containers are provisioned,
with narrow operator/release-identity data roles, shared keys disabled, deny-by-
default firewall, versioning and 30-day soft deletion. A real infinite-lease
contention/renewal/release test passed on the rehearsal blob; it is unlocked.
No production lock, app deployment, workflow disable, DNS/TLS change, state
transfer or catalog write occurred. CI network/identity access remains unproven.

An authenticated SCM adapter draft, private filesystem status/drain channel and
bounded protected-state capture are prepared locally. **418 target-Linux tests
pass**; offline runtime checks cover single-worker identity, auth, persistent
drain/state, fresh restart and SIGTERM. Adapter provenance retrieval, actual
backup/restore, live SCM ownership, restart/rollback and cleanup rehearsal remain
open; there is no runnable production CLI/workflow. No commit/push was made.

TLS public certificate is present and valid for the wildcard through 2027-04-18;
the user will provide its matching private key or PFX/P12 path. The disposable
write-canary/cleanup scope is approved but has not run. Legacy workflow remains
active and old writers uncontained; pilot mode remains `hold`. Production still
serves v1.0.5 / `0ddfd05` on the unchanged legacy CNAME.
See [PRODUCTION_RELEASE_RUNBOOK.md](PRODUCTION_RELEASE_RUNBOOK.md) and
`cutover-evidence/2026-10-23-release-storage-and-controls.json` for current gates.

### Earlier local preparation (historical evidence)

Credential persistence/precedence, allowlisted slot telemetry, authenticated
production mount identity and a fault-tested release-policy core are prepared.
See [PRODUCTION_RELEASE_RUNBOOK.md](PRODUCTION_RELEASE_RUNBOOK.md).
The core is intentionally not connected to Azure/CI: a real authenticated adapter,
durable lease/backup integration and supervised recovery proof remain required.
No commit, push, deployment, cloud setting, credential, DNS or catalog change was
performed. Legacy containment, protected transfer, TLS and named write canary are
still open gates. Local evidence is in `cutover-evidence/2026-10-23-preparation.json`.
Final target-runtime suite: **325 passed** (network disabled, UID/GID 65532).
Restart/persistence/auth/SIGTERM smoke passed; fresh image security gate passed
with the existing eight reviewed OS findings and zero unreviewed high/critical
findings. Exceptions were not extended. This is an uncommitted local image,
not a registry release receipt or live production acceptance.

**Production-cutover preflight completed 2026-10-23: NO-GO pending preparation.**
Live production and DNS are unchanged; pilot remains healthy and on `hold`.
See [PRODUCTION_CUTOVER_PREFLIGHT.md](PRODUCTION_CUTOVER_PREFLIGHT.md) for the
legacy-writer/drain gap, split state histories, production credential/configuration
requirements, DNS/TLS preparation, per-slot telemetry and production release lock.
This was read-only investigation; no application fixes or cloud changes were made.

**Isolated read-only container pilot PASSED with approved in-place promotion.**
Five fresh complete releases passed with 255 freshly executed tests each.
Median time to verified main: 266.88s (4m27s); median complete CI including
cleanup: 281s (4m41s). Initial queues were 3–5s; all ten rollouts were 35.50–55.10s.
Final build `39914306153-1` / commit `f7c58f0` / digest `3a7a7c24…` is healthy
on both pilot slots. Real sign-in, visible v2.0.0, catalog/thumbnails, read-only
status and actual telemetry ingestion are verified. Independent Kudu VFS state
hashes match the original main/staging identities. No temporary CI ingress remains.

Pilot mode is now `hold` after the requested measurement series. Public production
remains v1.0.5 / `0ddfd05`, its IONOS CNAME is unchanged, and remote `main` is
unchanged. This pilot performed no catalog writes, backfills, production shutdown or DNS cutover.
See [PILOT_ACCEPTANCE.md](PILOT_ACCEPTANCE.md) for every timing, retained failure,
recovery evidence, artifact-retention correction and maintenance follow-up.

## Implementation history (superseded by final acceptance above)

The user approved staging validation followed by the same tested digest update
in place, preserving main-slot state/settings and accepting a brief restart.
One verified rollback is permitted; ambiguous updates require reconciliation.
Revised local and recovery checks passed before resuming the measured series.

In-place prior-digest restoration passed on both pilot slots (33.69s staging,
54.22s main), preserving state and every setting/credential. A first rehearsal
stopped on Azure's changing audit timestamp; only that metadata is now excluded
from configuration comparison, and the failed receipt is preserved. All 251
tests pass locally and on target Linux in CI `39909715224`, including image
smoke, SBOM and the existing security gate. Failed-start recovery passed in
100.57s; a confirmed `ImagePullFailure` recovered once in 83.84s. Actual automatic
main rollback also passed: a forced gate failure after a healthy candidate
update restored the prior approved digest exactly once in 41.96s, preserving
state and credentials. Five complete timed releases subsequently passed.

A forward slot swap exposed a state-ownership mismatch:
the two pilot `/home` sentinels exchanged hostnames with the content. Runtime and
independent Kudu VFS hashes agree. No files were lost and legacy production/DNS
were untouched. Reverse-swap recovery PASSED in 84.70 seconds against the
original image/state checkpoint, including both nonroot/auth checks. Approval changes promotion to tested-digest updates
in place with a bounded restart/one rollback, rather than adding unapproved
external storage. See PILOT_ACCEPTANCE.md. Automatic pilot deployments are held
after completed pilot acceptance; build-only validation stays enabled.

User approved the exact-image applicability review and requested unattended
execution until the pilot passes. All eight candidate package findings have
individual validation receipts. The ncurses PoC aborts the unpatched control
and passes on the DHI binary; signed vendor evidence confirms the backport.
The four util-linux CVEs concern components absent from the final image.

An exact-image, 30-day-expiring gate and 31 negative/positive regression tests
have been implemented. Raw scans are preserved with 90-day retention. Clean CI
passed before provisioning. Production, DNS, main and the shared plan
remain unchanged. See CONTAINER_VALIDATION.md for current evidence; earlier red
scan results below are historical and remain retained.

After the user unlocked 1Password, signed commit `99ab28b` was pushed to the
pilot branch. CI `39901906332` passed in 70 seconds, including all 197 tests,
runtime smoke, SBOM and the image-bound applicability gate. Signing was not
disabled. Production remains `v1.0.5` / `0ddfd05`.

The approved infrastructure was validated with Bicep and ARM validation. What-if
showed only new pilot resources/roles; all existing resources were Ignore.
Deployment `image-library-container-pilot` succeeded after aligning the staging
slot kind with Azure's normalized `app,linux` parent. Created dedicated P2v3
one-instance plan, Premium ACR (ABAC, admin/anonymous access disabled), new app
and staging, separate build/deploy OIDC identities and narrowly scoped roles.
GitHub build/pilot environments allow only `perf/container-pilot`.

Pilot endpoints are IP-restricted to the operator, with per-run temporary CI
access removed on completion. Runtime pulls use system-assigned identities with
repository-only Reader; publisher has Writer only for release/cache repos and
registry control-plane Reader. Deployment identity is Website Contributor on
the new app only. No permission on the legacy app or Pete was granted.

Configuration copy is verified for both new slots, and exactly two pilot sign-in
callback URIs were added while retaining the production callback. Read-only is
enabled, ingestion and authentication bypass are disabled. Secrets never enter
repository files or CI artifacts. All 205 local tests pass. The pilot pipeline reuses the same validation
script and binds the published registry manifest to the tested/scanned config.
This is a workflow provenance receipt, not a claim of a signed SLSA attestation.
Azure readiness alone does not satisfy SSO, state, telemetry, rollback or speed
acceptance. Main, production, DNS and catalog writes remain untouched.

First pilot run `39903322640` published digest
`sha256:e76392db0b8c01ae857856a81b91ab30146cc32fb4c95195212448820f057253`
after all 205 tests and security gates passed. Deployment failed before any
slot mutation: the runner CLI does not expose `appServicePlanId` under the same
name as the local CLI. The target guard now accepts either documented plan-ID
shape, requires the exact resource/plan IDs, and rejects conflicting fields.
Eight regression cases cover compatibility and incorrect resource targets.

Corrected commit `942685e`, pilot run `39903706929`, passed build, scan, publish
and Azure staging deployment. Digest
`sha256:bdd6e501308d5f41c5e1b0deb87f447ea4e258d8c8bdf2844f0b67c502ee1243`
was ready with matching commit/build and telemetry enabled. Deployment helper
elapsed 27.93 seconds (includes preflight; not yet a separately timed pull).
Temporary CI IP access was removed. Real Entra sign-in in Edge succeeded, the
homepage visibly displays v2.0.0, and catalog categories/thumbnails loaded.
Application Insights received 45 requests and 28 dependencies for this build;
the sole failed request was an unmatched 404, with zero failed dependencies.
This is a partial pilot pass, not final acceptance. Persistence across Azure
restart/swap, recovery rehearsals and controlled performance comparison remain.

A read-only pilot-only sentinel is now covered by tests so actual mounted-state
identity can be compared across new image deployments, restarts and swaps.
The sentinel never follows symlinks or overwrites an existing invalid file.
It is disabled by default and must be disabled before production writes resume.

Persistence-enabled commit `68ae9ed`, run `39904263261`, passed all 219 tests,
scan/publish and Azure readiness. Actual Azure UID/GID are 65532. The runtime's
state ID `c4ed33732aa65098c8b4536a5c8ef7fc1dc804df435a147741df59b965a38115`
matches the sentinel hash retrieved independently from the slot's Kudu VFS,
confirming the application writes the mounted persistent storage, not just an
image-local directory. No application/catalog files were altered by this probe.

Prepared a separate same-P2v3 source/Oryx baseline workflow. It targets only the
currently empty NEW app's production slot, leaves the container staging slot
intact, requires read-only/no-bypass settings, and refuses to replace an existing
container. The source archive uses the existing allowlist and single-worker
startup. Temporary CI IP access is removed in cleanup. Legacy production and
DNS remain unchanged; this is solely the approved controlled comparison.

Same-plan source baseline `39904604111` passed. Both modes use commit `8e46014`;
20 interleaved authenticated warm reads each returned exactly the same 280
records. Browser p95 was 193 ms for both modes; median source 128.5 ms vs
container 124.5 ms. Actual Insights ingestion confirms source and container
requests with zero API failures. Detailed evidence and remaining gates are in
[PILOT_ACCEPTANCE.md](PILOT_ACCEPTANCE.md). Rehearsal helpers have 228 passing
local regression tests. The CI preflight now waits for existing persistent-state
identity instead of treating temporary ingress-propagation errors as no state.

## Container migration

- Source: `PP-App-Serv` and staging on shared `proxima-plan-s1`, West US 2.
- Proposed target: new Image Library app and staging on dedicated Linux P2v3, one instance; ACR Premium; existing subscription and `PP-Resources`.
- User constraints: speed over cost; one current user; necessary production downtime permitted.
- Detailed plan: [CONTAINER_IMPLEMENTATION_PLAN.md](CONTAINER_IMPLEMENTATION_PLAN.md).

## Phase status

- [x] Identify current app, hosting and deployment path.
- [x] Assess source code, background writers, persistent paths and container prerequisites.
- [x] Present proposed rollout, acceptance gates and rollback design in the local plan.
- [x] User approved the container implementation plan and necessary downtime.
- [ ] Pre-migrate: protected configuration/state inventory and validated DNS/TLS rollback.
- [x] Implement and verify container image and isolated pilot.
- [ ] Execute approved maintenance-window cutover.
- [ ] Validate public behavior, telemetry and measured performance.

## Important findings

An in-place dedicated-plan move is not established: the app retains the legacy `proxima-connector-rg-WestUS2webspace-Linux` webspace, and that original resource group no longer exists. The proposed new-app route avoids depending on that move. The existing app/plan are not deleted; Pete remains untouched.

Production and staging both configure the same ingest folder, and importing the web application can start a writing/deleting poller. The pilot and every nonproduction slot must have writers disabled; a single user does not prevent duplicate background jobs. This is a detected risk, not evidence that duplication occurred.

Pilot implementation is complete on `perf/container-pilot`; `main` and production remain unchanged. Writer/drain controls, persistent-state paths and build identity have local and live validation evidence. The approved isolated Azure resources are provisioned and the pipeline has passed the measured series. Public cutover preparation remains separate. No DNS change or catalog write has been made.

IONOS is the confirmed DNS provider. On 2026-10-22 the user supplied an authenticated Edge session; the `library` CNAME and `asuid.library` TXT were verified in the DNS panel. The CNAME remains `pp-app-serv.azurewebsites.net`. DNS access is no longer a blocker; TLS, state transfer and pilot acceptance gates remain outstanding. The unrelated root, mail, Pete and other subdomain records are outside scope.

## Historical local implementation evidence (superseded by current checkpoint)

- Homepage/shared application version changed from `v1.0.5` to `v2.0.0` at the user's request. Exact homepage badge and API value covered by tests. Public production still reports `v1.0.5` / `0ddfd05`.
- 155 local Python 3.12 tests passed, including read-only GET/SSE/POST guards, admin/origin checks, detached-worker/child drain accounting and immutable build identity.
- Linux/amd64 Docker test stage passed its initial 150-test run and the expanded 155-test suite on the selected Debian 13 base. `git diff --check` and both workflow files passed actionlint 1.7.12.
- Both Python 3.12/Debian 12 and Python 3.12/Debian 13 final images passed network-disabled black-box checks: UID 10001, read-only root filesystem, exact build/version readiness, anonymous home redirects to login, WebP support, expected `.env`/`.git`/test-data/test-tool paths absent, state retained across restart, SIGTERM exits 0. This is local-volume evidence, not proof of Azure mount behavior.
- Build-only GitHub workflow added with pinned checkout/upload Actions, SBOM and a fail-closed HIGH/CRITICAL scan. It has no Azure credentials, OIDC, registry publish or deployment permissions. Legacy source deploy now supports an explicit repository release mode (`source`, `hold`, `container`; empty retains existing source behavior).
- Scanner: Trivy 0.76.1, image digest `sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c`, database fetched 2026-10-23 UTC. Debian 12: 63 HIGH/CRITICAL package findings, 16 distinct CVEs, including two CRITICAL. Debian 13: 44 HIGH findings, eight distinct CVEs, zero CRITICAL. Both scans reported zero HIGH/CRITICAL Python-package findings. These are scanner findings, not a claim that all are exploitable through this application.
- Selected the official digest-pinned Debian 13/Python 3.12.15 candidate for further validation. OS scan gate still FAILS. No ignore file, `--ignore-unfixed`, blanket waiver or lowered severity threshold was added. Do not provision/promote a release until remaining findings are remediated or individually reviewed under an explicitly approved expiring exception policy.
- Remaining Debian 13 CVEs: `CVE-2025-69720`, `CVE-2026-9538`, `CVE-2026-16742`, `CVE-2026-54369`, `CVE-2026-76642`, `CVE-2026-78408`, `CVE-2026-78409`, `CVE-2026-78410`. Scanner reports no fixed Debian package versions for them. Review vendor advisories and actual runtime exposure before proposing any exception.

Raw local scan evidence: `/tmp/image-library-container.cufej1/vulnerabilities.json` and `vulnerabilities-trixie.json`. Local preview images are explicitly marked `local-uncommitted-*`; they are NOT release artifacts. A release must be rebuilt from the committed branch by CI with the exact Git SHA/run ID and verified digest.

Vendor advisory references and next decision are recorded in [CONTAINER_VALIDATION.md](CONTAINER_VALIDATION.md). The image gate is deliberately red; publishing a build-only pilot branch does not approve a production exception or deploy to Azure.

Pilot checkpoint `83f2e18` pushed. First CI run `39894903794` passed tests/build/runtime smoke, but its SBOM step failed on scanner-cache permissions before vulnerability scanning. Commit `f377a5b`, run `39895498587`, verified the UID/GID correction: tests/build/smoke/SBOM passed, then the real vulnerability gate failed on 44 HIGH findings / eight CVEs.

## Approved minimal-base adjustment — 2026-10-22

- User approved the DHI base-image adjustment; no vulnerability exception was approved.
- Dockerfile now pins matching DHI Python 3.12.15 / Debian 13 builder/runtime digests. The shellless Python entrypoint execs one Gunicorn master; the legacy source startup remains unchanged. Runtime UID/GID is the vendor's 65532. Production Python dependencies are unchanged.
- 166 tests passed locally and on the actual minimal OS/non-root identity with networking disabled. Exact final-image smoke passed, including auth, restart persistence, native WebP, CA trust, real PID 1 Gunicorn and bounded SIGTERM. Azure volume permissions remain a separate pilot gate.
- Local Docker image size reduced from 327,465,556 to 237,144,654 bytes (about 28%). No application-speed or Azure deploy-time improvement is claimed yet.
- Full application-image scan reduced findings from 44 to eight HIGH package findings (five distinct CVEs); zero CRITICAL and zero HIGH/CRITICAL Python findings. **The unchanged release gate still fails.** Raw evidence: `/tmp/image-library-dhi-validation.poBonM/`.
- No VEX suppression, ignore list, severity relaxation or exception policy has been enabled. Review residual package/function applicability separately before seeking a narrow, expiring exception. No Azure mutation, DNS change, main merge or production deployment has occurred.
- Commit `bbbf71c`, [CI run 39896763400](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39896763400), independently passed base pulls, all 166 tests, final build, exact-build smoke and SBOM generation. The raw scan failed on the same eight HIGH findings / five CVEs. Evidence artifact retained; no registry publish or Azure deploy took place. See [CONTAINER_VALIDATION.md](CONTAINER_VALIDATION.md) for the next package-specific applicability review and a newly distinguished vendor ncurses patch statement. No suppression is enabled.
