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

The Dockerfile now pins the Debian 13 candidate. Findings repeat across binary packages originating from the same source package; 44 findings are not 44 independent bugs. A scanner severity is not proof of an externally exploitable application path. Conversely, a non-root process or absent direct source-code reference does not by itself prove safety.

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
- Vendor OpenVEX metadata exists for those five CVEs in `docker-hardened-images/advisories` at commit `5af0d37bd8bb54871bd74a4627439b6db56f7f6d`. It marks them `not_affected`, citing Debian no-DSA decisions and inability for an adversary to control the vulnerable code. A no-DSA classification alone is not proof that vulnerable code is absent.
- No VEX suppression or risk exception was applied. The application's Dockerfile still uses the strict-scan Debian 13 candidate, not DHI.

Proposed next adjustment: adopt the vendor-maintained minimal runtime with a matching builder, replace the Bash entrypoint with exec-form Python/Gunicorn startup, rerun the full suite against the actual runtime, and add a reviewable vulnerability-applicability policy. Preserve the unfiltered scan; accept only exact-image/package vendor assessments corroborated for this workload, with a review deadline. New, unmatched, expired or exploitable findings remain blocking. This is a policy/base-image adjustment to present before adoption, not permission to bypass the current failing gate.

[Docker's Python migration guidance](https://docs.docker.com/dhi/migration/examples/python/) and [scanner/VEX guidance](https://docs.docker.com/dhi/how-to/scan/) describe the runtime and scanning requirements. CI access to the DHI registry must also be verified; successful access on the developer's machine does not prove runner access.
