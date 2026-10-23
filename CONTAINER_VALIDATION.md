# Container validation checkpoint — v2.0.0

2026-10-22 Pacific / 2026-10-23 UTC. No production cutover performed.

## Passed locally

- 155 regression tests on Python 3.12, also executed in the Linux/amd64 Docker test stage.
- Exact homepage badge `v2.0.0` and matching `/api/version`.
- No-network final-image smoke: non-root UID 10001, read-only root, authentication redirect, readiness with exact build identity, WebP, persistent state through restart, graceful SIGTERM exit 0.
- Pilot write guards reject unknown GET routes, legacy SSE writes and POST writes. SharePoint mutation methods reject read-only calls before token acquisition/network.
- Drain denies new work and tracks already admitted background threads/maintenance child processes after browser disconnect.
- Workflow lint and whitespace checks. Validation workflow has no deploy/publish credentials.
- Package-inventory SBOM generated. This inventory is separate from, and not a substitute for, the vulnerability scan.

## Release gate not passed

Trivy 0.76.1, freshly downloaded database, reported:

| Candidate | HIGH package findings | CRITICAL package findings | Distinct HIGH/CRITICAL CVEs | Python HIGH/CRITICAL findings |
| --- | ---: | ---: | ---: | ---: |
| Official Python 3.12.15 / Debian 12 | 61 | 2 | 16 | 0 |
| Official Python 3.12.15 / Debian 13 | 44 | 0 | 8 | 0 |

The first checkpoint pinned the Debian 13 candidate; the approved minimal-image adjustment below supersedes it. Findings repeat across binary packages originating from the same source package; 44 findings are not 44 independent bugs. A scanner severity is not proof of an externally exploitable application path. Conversely, a non-root process or absent direct source-code reference does not by itself prove safety.

Remaining advisories, checked against the Debian security tracker:

| Source component | Advisory | Vendor description / investigation scope |
| --- | --- | --- |
| ncurses | [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | Overflow in `infocmp`; binary present in the candidate, no direct application invocation found |
| Perl | [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | `Archive::Tar` memory exhaustion; expected module path absent, package-level absence still needs formal confirmation |
| systemd | [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | `systemd-homed` privilege escalation; daemon absent at expected path, libraries present |
| acl | [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | Privileged pathname-based ACL operations follow symlinks; review callers/privileges |
| util-linux | [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | Mount helper failure / privileged post-mount hooks |
| util-linux | [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | Root `nsenter --join-cgroup` descriptor inheritance |
| util-linux | [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | Restricted subdirectory mount traversal |
| util-linux | [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | Restricted bind mount source race / ownership changes |

The candidate contains `mount` with a setuid bit, and `nsenter`; do not assume Azure enforces the local smoke test's `no-new-privileges`/capability flags. These flags were local validation controls, not deployed Azure settings. No production exception has been approved.

## Next decision / safety boundary

Do not advance to Azure pilot/promotion under the current failing gate. First choose a remediation path: remove unnecessary privileged runtime utilities through a maintained minimal-image design and retest, or conduct package/function-level applicability review and request narrowly scoped, dated exceptions for proven non-applicable or accepted residual findings. Do not graft unstable Debian packages into this stable image or silently use `--ignore-unfixed`.

Any approved exception must identify CVE, package, image digest, evidence, compensating controls, approver and expiry. New findings and expired exceptions must still fail. Preserve raw scan output alongside any filtered decision report. No blanket acceptance is implied by permission for downtime.

Local reports: `/tmp/image-library-container.cufej1/`; `vulnerabilities-trixie.json` and `sbom-trixie.cdx.json`. CI independently rebuilds and scans the committed branch; local `local-uncommitted-*` images cannot be promoted.

## Still unverified

Azure-mounted `/home` permissions/persistence, private registry pull/OIDC, real SSO callback, telemetry ingestion, forward/reverse swap, same-compute performance, protected state transfer and DNS/TLS rollback. Production remains on `0ddfd05`, `v1.0.5`. IONOS access is verified, but DNS records remain unchanged.

## CI checkpoint and minimal-image investigation

Commit `83f2e18` was pushed only to `perf/container-pilot`. [Run 39894903794](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39894903794) passed the regression suite, image build and offline runtime smoke, then failed before the vulnerability gate because the scanner could not create its cache in a runner-owned bind mount. The corrective workflow change runs the scanner as the runner's UID/GID while keeping all capabilities dropped. It does not relax filesystem permissions or scanning policy.

An additional read-only/offline investigation pulled Docker's minimal runtime image:

- `dhi.io/python:3.12-debian13@sha256:a67245096d56c6ce891b9bec78a8090850907af9314185597c6b5d75438ca999` (Python 3.12.15, UID 65532, no shell/package manager).
- The matching builder digest is `sha256:a3d43f90a9e72d5fa53efa18c692f020604c95e89bc7de62aa9cafad7ee9c795` for `dhi.io/python:3.12-debian13-dev`.
- Raw base-only scan: eight HIGH package findings across five distinct CVEs, zero CRITICAL. This is not an application-image scan and not a passing release gate.
- Vendor OpenVEX metadata exists for those five CVEs in `docker-hardened-images/advisories` at commit `5af0d37bd8bb54871bd74a4627439b6db56f7f6d`. It contains `not_affected` statements citing Debian no-DSA decisions and inability for an adversary to control the vulnerable code. A no-DSA classification alone is not proof that vulnerable code is absent. Later inspection also identified a separate patch-applied statement for ncurses (see below); the initial summary did not distinguish these overlapping statements.
- No VEX suppression or risk exception was applied. At this checkpoint the application's Dockerfile still used the strict-scan Debian 13 candidate, not DHI.

Proposed next adjustment: adopt the vendor-maintained minimal runtime with a matching builder, replace the Bash entrypoint with exec-form Python/Gunicorn startup, rerun the full suite against the actual runtime, and add a reviewable vulnerability-applicability policy. Preserve the unfiltered scan; accept only exact-image/package vendor assessments corroborated for this workload, with a review deadline. New, unmatched, expired or exploitable findings remain blocking. This is a policy/base-image adjustment to present before adoption, not permission to bypass the current failing gate.

[Docker's Python migration guidance](https://docs.docker.com/dhi/migration/examples/python/) and [scanner/VEX guidance](https://docs.docker.com/dhi/how-to/scan/) describe the runtime and scanning requirements. CI access to the DHI registry must also be verified; successful access on the developer's machine does not prove runner access.

## Approved base-image adjustment — 2026-10-22

The user approved the minimal-base adjustment, not any vulnerability exception. The raw HIGH/CRITICAL gate remains unchanged. The previous [CI run 39895498587](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39895498587) passed 155 tests, final-image smoke and SBOM generation; the corrected scanner then failed the gate with the same 44 HIGH findings / eight CVEs as the local Debian-slim scan.

The Dockerfile now uses the pinned DHI runtime and matching builder above. `scripts.container_start` validates the port and execs Gunicorn without a shell, retaining one worker and the legacy timeouts/logging. Production requirements are unchanged. The application venv is built without pip; the vendor's system Python still contains pip, so this is not a claim that every package-management module has been removed. No OS packages are manually stripped or replaced.

Local validation of `image-library:local-dhi`:

- **166 tests pass** on local Python 3.12 and on the actual shellless runtime OS, UID/GID 65532, with test execution networking disabled. New coverage verifies invalid ports fail before exec, single-worker startup arguments, and a real Python maintenance subprocess over the existing SSE path.
- The exact final-image smoke passes with no network, read-only root, dropped capabilities and no-new-privileges: v2.0.0/exact build identity, auth redirect, WebP, CA trust, PID 1 Gunicorn, immutable `/app`, absent shell/mount/nsenter/apt/dpkg, no setuid/setgid utilities in the standard executable directories, state persistence and SIGTERM exit 0. Tests and pip are not importable in the application venv. Azure enforcement of these Docker smoke flags is still unverified.
- Local image size is **237,144,654 bytes**, versus **327,465,556 bytes** for the previous Debian-slim candidate, about 28% smaller. These are Docker-reported local image sizes, not network transfer sizes or an application performance benchmark.
- Fresh Trivy scan of the **complete application image**: **eight HIGH package findings across five CVEs**, zero CRITICAL, zero HIGH/CRITICAL Python-package findings. The scanner reports 41 OS packages, versus 87 previously. It uses vendor embedded inventory for the minimal OS and warns that third-party SBOM data may be inaccurate; filesystem checks corroborate the key absent utilities but do not establish complete scanner coverage.
- Remaining findings: `CVE-2025-69720` on `libncursesw6`, `libtinfo6`, `ncurses-base`, `ncurses-bin` version `6.5+20250216-2+dhi4`; `CVE-2026-76642`, `CVE-2026-78408`, `CVE-2026-78409`, `CVE-2026-78410` on `libuuid1` version `2.41.5-0+deb13u1+dhi3`. No fixes are listed by this scanner. No VEX filtering or exception has been enabled. **Gate still fails.**
- An empty Docker credential-config manifest lookup succeeded for the runtime digest. This is not yet proof of clean-runner image-layer access; the committed CI build must verify both base pulls.

Local raw scan/SBOM: `/tmp/image-library-dhi-validation.poBonM/`. The preview is marked `local-uncommitted-v2-dhi` and is not deployable. Next: rebuild the committed branch in CI, review residual findings at package/function level, and obtain separate approval for any exact-image, expiring applicability exception before enabling it. Production and DNS remain unchanged.

### Independent CI result

Implementation commit `bbbf71cd2e822425c5ade79db2bb887883cb898f`, [run 39896763400](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/39896763400), completed in 1m33s. Clean-runner base pulls, **166 tests**, final image build, exact-build authentication/restart/storage smoke and SBOM generation all passed. The HIGH/CRITICAL gate failed as designed: **eight HIGH findings, five CVEs, zero CRITICAL, zero HIGH/CRITICAL Python findings**. Raw evidence was retained as `container-validation-39896763400-1`; local copy is `/tmp/image-library-dhi-validation.poBonM/ci-39896763400/`. This was build-only and did not publish an image or deploy. No new registry credentials were needed by this run; future access policy changes remain a possible dependency.

Residual triage, **not an approved suppression**:

- `libuuid1` is present; `mount`, `nsenter` and `libmount.so*` were absent in a filesystem search under `/usr` and `/opt` in the local final image. The four util-linux advisories above describe mount/nsenter paths, not UUID generation. This supports a component-level non-applicability review; it is not a general waiver for the util-linux source package or future images.
- The [pinned vendor VEX](https://github.com/docker-hardened-images/advisories/blob/5af0d37bd8bb54871bd74a4627439b6db56f7f6d/vex/python/dhi-python.vex.json) includes statement `cbbb37c0-641d-4131-9633-04a23515c025` for `CVE-2025-69720`, with `inline_mitigations_already_exist`. It explicitly says the upstream 20251213 ncurses fix was applied to source package `6.5+20250216-2+dhi4`, matching the installed package family. `infocmp` is still present. Corroborate image/package provenance and patched behavior before accepting this disposition; do not treat the scanner's missing fixed-version field as proof that Docker's backport is absent, or blindly apply the entire vendor VEX file.
- CI also warned that pinned `actions/upload-artifact@v4` uses Node 20 and was forced onto Node 24. Artifact upload succeeded. Update that Action in a separate reviewed maintenance change; it was not the gate failure and is not part of this base-image adjustment.

The next release decision is a narrowly scoped, independently evidenced applicability policy, not another broad downgrade of the scanner threshold. No such policy has been enabled. Production `/readyz` was rechecked and remains healthy on `v1.0.5` / `0ddfd05`.
# Approved applicability review — 2026-10-22 Pacific

The user approved executing the recommendation and continuing unattended until
the pilot passes. This does not waive unresolved findings or authorize cutover
before pilot acceptance.

The eight residual package findings were individually validated. Docker's
signed image SBOM identifies the exact DHI revisions. Signed VEX artifact
`sha256:72c2c21e7502738d796cd269fcc780a025da33e25d8f3c60a72089dbdb1c7acf`
contains ncurses patch statement `cbbb37c0-641d-4131-9633-04a23515c025`.
The reporter's exact terminfo input crashes the unpatched Debian image with a
buffer-overflow abort; the real DHI `infocmp -i` completes successfully. The
other four CVEs target mount/libmount/nsenter, which are absent from the runtime;
the installed libuuid provides UUID symbols, not libmount symbols.

Docker Scout verified signatures but its VEX export panicked. Retrieval with
regctl preserved the raw payload, whose SHA-256 matches the layer in that signed
manifest. This is not treating an unsuccessful export as an overall successful
command. Neither the generic no-DSA statements nor all vendor VEX entries are
automatically accepted.

`security/container-review.json` now expresses the narrow review, expiring
**2026-11-21 23:59:59 UTC**. The gate verifies all archive layer hashes, exact
base layers, five binary hashes, absence of affected utilities and set-ID files,
exact source/build/config identity, scanner version and scan freshness, then
allows only the eight exact HIGH package/CVE/version tuples. New findings,
changed evidence, available fixed versions, missing scans and expiry fail closed.
The raw Trivy report and finding exit code remain intact, separately from the
applicability result. Evidence retention is now 90 days, beyond review expiry.

31 new tests cover acceptance, policy expiry, mismatched identities, altered
binaries, added vulnerable components, new CVEs/packages/versions/severities,
scanner errors represented by missing/invalid results, and archive integrity.
Individual reports, receipts, signed SBOM/VEX and PoC results are retained in the
target-bound Codex Security artifact collection. This review is not a claim
that all application vulnerabilities have been eliminated. CI and Azure pilot
acceptance remain separate gates.
