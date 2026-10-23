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
