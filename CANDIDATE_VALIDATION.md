# New candidate rehearsal and staging validation

Authorized scope, October 24, 2026 UTC: review and publish a new immutable
candidate, exercise the isolated synthetic rehearsal, then deploy that same
digest to read-only staging and validate actual authenticated reads. Production
image/settings, production write-resume enablement, ingestion and schedules are
unchanged. Private unattended networking remains deferred.

## Reviewed source

- Stopped image changes and nonce-owned cleanup now require named old-container
  termination, protected state/configuration checks and one fresh runtime.
- Post-cleanup resume uses fresh-boot binding and protocol 2 durable request
  retirement. Ambiguous outcomes retain the lease and prohibit mutation replay.
- The defined local failure matrix is in `RELEASE_FAILURE_MATRIX.md`.
- Scoped four-file security review completed with no reportable findings. It
  does not prove effective cloud permissions or live Azure behavior.
- Rehearsal additionally exercises candidate stopped cleanup/restart, stale-boot
  rejection and exact one-shot resume with empty-channel readback. Its physical
  target remains only the synthetic rehearsal app. It does not claim full
  production-controller end-to-end or production-provider writable acceptance.

## Pending gates

1. Signed source review/CI and main integration; no automatic deployment.
2. One fresh manual builder; authenticate receipt/digest and disable builder.
3. Pin the new candidate in the rehearsal harness, review/test it, run isolated
   rehearsal with bounded temporary single-runner access, verify rollback,
   stopped app, absent owned files, unlocked lease and removal of temporary rules.
4. Reverify current production/staging identities, containment and read-only
   staging configuration. Hold the release lease for a bounded staging-only
   cold deployment; preserve configuration/state and prohibit production writes.
5. Validate exact staging identity, authentication, catalog/thumbnail reads and
   matched baseline/candidate measurements. Record limitations honestly; health
   alone is not performance acceptance. Production promotion remains separate.

This document is a work-in-progress checkpoint, not a successful deployment receipt.
