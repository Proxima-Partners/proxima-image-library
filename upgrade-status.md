# Upgrade status

Updated: 2026-10-22 (America/Los_Angeles).

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

Implementation is in progress on `perf/container-pilot`; `main` and production remain unchanged. Writer/drain controls, persistent-state paths and build identity have local validation evidence below. The checkpoint is isolated to the pilot branch and its build-only workflow. No Azure resource mutation, DNS change or catalog write has been made during this implementation stage.

IONOS is the confirmed DNS provider. On 2026-10-22 the user supplied an authenticated Edge session; the `library` CNAME and `asuid.library` TXT were verified in the DNS panel. The CNAME remains `pp-app-serv.azurewebsites.net`. DNS access is no longer a blocker; TLS, state transfer and pilot acceptance gates remain outstanding. The unrelated root, mail, Pete and other subdomain records are outside scope.

## Local implementation evidence

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

Pilot checkpoint `83f2e18` pushed. First CI run `39894903794` passed tests/build/runtime smoke, but its SBOM step failed on scanner-cache permissions before vulnerability scanning. A runner UID/GID correction is being validated; no scan result is inferred from that failed job. Docker's shellless hardened Python base was also inspected/scanned separately; it still needs a scoped, reviewed VEX/applicability policy and startup changes before adoption. No such policy has been enabled.
