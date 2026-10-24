# Main integration checkpoint

2026-10-23 (America/Los_Angeles). The user's "continue to completion" after the
main-integration approval gate is being applied to reviewed source integration.
It does not grant new Azure roles/network access, deployment, write-canary scope
or production automation activation. Those gates in `OPERATIONS_ACTIVATION.md`
remain separate.

## Reviewed scope

- Legacy main `0ddfd050160f5363a1ebb87ade588509b7a426e0` is an ancestor of the
  implementation branch: no divergent main commits or merge conflicts observed.
  Thirty commits include the accepted container/cutover history plus the new
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
  This is not a reason to bypass validation: wait for both complete PR checks,
  require the reviewed exact head, and recheck main before merging. Adding access
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
are unchanged. Fresh PR container/security/browser and T1/audit checks are required.

## Remaining release gates

Main integration is not production release acceptance. The 24-hour observation
cannot complete before approximately October 24 at 14:08 PDT and needs actual
telemetry evidence, not just elapsed time. A new reviewed container builder,
trusted builder policy, CI identity/network proof, isolated recovery rehearsal,
first supervised normal release and separate opt-in activation remain pending.
No watched-folder ingestion, repair, backfill, DNS/tier change or legacy cleanup.
