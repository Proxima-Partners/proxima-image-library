# Upgrade status

Updated: 2026-10-22 (America/Los_Angeles).

## Current execution checkpoint

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
- [ ] Implement and verify container image and isolated pilot.
- [ ] Execute approved maintenance-window cutover.
- [ ] Validate public behavior, telemetry and measured performance.

## Important findings

An in-place dedicated-plan move is not established: the app retains the legacy `proxima-connector-rg-WestUS2webspace-Linux` webspace, and that original resource group no longer exists. The proposed new-app route avoids depending on that move. The existing app/plan are not deleted; Pete remains untouched.

Production and staging both configure the same ingest folder, and importing the web application can start a writing/deleting poller. The pilot and every nonproduction slot must have writers disabled; a single user does not prevent duplicate background jobs. This is a detected risk, not evidence that duplication occurred.

Implementation is in progress on `perf/container-pilot`; `main` and production remain unchanged. Writer/drain controls, persistent-state paths and build identity have local validation evidence below. The approved isolated Azure resources are now provisioned; the first publish/deploy pipeline is next. No DNS change or catalog write has been made.

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
