# Main integration checkpoint

2026-10-23 (America/Los_Angeles). The user's "continue to completion" after the
main-integration approval gate is being applied to reviewed source integration.
It does not grant new Azure roles/network access, deployment, write-canary scope
or production automation activation. Those gates in `OPERATIONS_ACTIVATION.md`
remain separate.

## Completed integration: October 23, 21:49 PDT

[PR #4](https://github.com/Proxima-Partners/proxima-image-library/pull/4) merged
reviewed head `57bd4f18a401aeae7321dad4236cca2063971f62` into main as
`21a66fd754b7269b87d31ba58ed9de3b8db0d670` at 2026-10-24 04:49:39 UTC.
The merge was pinned to that head after all three checks passed and main was
rechecked. The merged tree exactly matches the reviewed head.

- Push [container validation 40063679347](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/40063679347): passed, job 1m32s.
- PR [container validation 40063703160](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/40063703160): passed, job 1m45s; 633 target-runtime tests, 13 browser/workflow checks, runtime/release-channel smoke, SBOM and zero unreviewed HIGH/CRITICAL findings.
- PR [T1 and dependency audit 40063703151](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/40063703151): passed, job 55s; 633 tests and no known vulnerabilities reported by pip-audit.

All running job pages were opened in Microsoft Edge. The Node 20 warning is
resolved; PR container annotations were empty. Push artifact `12548283579` was
retrieved through authenticated bounded reads, its digest verified and its
expected seven-file ZIP layout confirmed without extracting files.

No workflow ran for the merge commit. Pilot mode is still `hold`, the legacy
deployment workflow is `disabled_manually`, and the new operations enablement
variables remain absent. A 04:49:52 UTC post-merge public probe passed health,
readiness, exact accepted version/build and admin HTTP 401 checks. Production
still serves `2ffc0ff` / `40019125172-1`; this does not prove authenticated user
flows, Azure configuration, representative performance or 24-hour telemetry.

## Reviewed scope

- Legacy main `0ddfd050160f5363a1ebb87ade588509b7a426e0` is an ancestor of the
  implementation branch: no divergent main commits or merge conflicts observed.
  Thirty-one commits include the accepted container/cutover history plus the new
  read-efficiency and release-control implementation. Historical evidence stays
  intact; source integration does not rebuild or replace deployed production.
- Reviewed runtime changes preserve authentication, environment-only Azure
  credentials, persistent non-secret state, read-only/drain controls, tracked
  background work, one-worker/one-instance limits and ingestion opt-in. The
  deployed accepted build remains `2ffc0ff` / `40019125172-1`.
- All three obsolete deployment entry points are refusal stubs. Current build/PR
  workflows have read-only contents permission and no Azure/OIDC login. New
  operations workflows require both main and explicit enablement variables.
  Only the existing pilot `hold` variable is configured; new enablements are absent.
- The repository currently has no main branch protection/ruleset requirements.
  Validation was not bypassed: all three checks completed, the reviewed exact
  head was required, and main was rechecked before merging. Adding access
  or protection rules is a separate administrative change, not silently included.

## CI dependency adjustment before merge

The non-failing Node 20 warning is addressed by pinning `upload-artifact` to
v7.0.2 (`cf430e0...`) and explicitly retaining ZIP `archive: true`. GitHub's
[v7 release notes](https://github.com/actions/upload-artifact/releases/tag/v7.0.0)
describe optional direct/unzipped uploads; these are deliberately not enabled.
The [v6 runtime change](https://github.com/actions/upload-artifact/releases/tag/v6.0.0)
introduced Node 24, which the v7.0.2 action manifest also declares.

The independent T1/dependency-audit workflow now pins checkout and setup-python
to Node-24-capable commit hashes, uses Ubuntu 24.04 and exact Python 3.12.15 to
match the target runtime. Both its full regression and strict dependency audit
remain intact. Application dependencies, security exceptions and base digests
are unchanged. Fresh PR container/security/browser and T1/audit checks passed.

## Remaining release gates

Main integration is not production release acceptance. The 24-hour observation
cannot complete before approximately October 24 at 14:08 PDT and needs actual
telemetry evidence, not just elapsed time. A new reviewed container builder,
trusted builder policy, CI identity/network proof, isolated recovery rehearsal,
first supervised normal release and separate opt-in activation remain pending.
No watched-folder ingestion, repair, backfill, DNS/tier change or legacy cleanup.
