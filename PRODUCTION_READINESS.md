# Production builder, CI access and recovery readiness

Approved 2026-10-23 PDT following the completed main integration. This approval
covers a new reviewed production builder, narrowly scoped CI access and isolated
recovery rehearsal. It does not activate production promotion, write resumption,
ingestion, schedules, a new catalog canary or legacy deletion.

## Execution plan

1. Add a manual-main-only builder using the existing publisher identity, fixed
   target runtime, fresh tests, exact-image smoke/security/SBOM, strict dependency
   audit and immutable registry digest. Keep publishing separate from deployment.
2. Review/merge its source, register its exact GitHub workflow ID and source hash
   in the receipt verifier, and restrict the publisher environment to main.
   Permit one fresh build, verify its authenticated artifact, then return the
   builder enablement flag to false. Do not rerun a published build.
3. Prove the release identity/network path without opening SCM/storage broadly.
   Inventory prior OIDC subjects, credentials, writers and branch restrictions.
   Any temporary network rule must be limited to one runner address, recorded,
   independently removed and verified. Preserve production settings and state.
4. Exercise isolated recovery using synthetic state, real CI identity/storage
   paths and explicit failure injection. Separate real provider observations
   from simulated ARM outcomes; neither unit tests nor simulation alone closes
   the live recovery gate. No new production canary or real-state restore.
5. Retain sanitized evidence and protected recovery records; stop on uncertain
   writes or incomplete cleanup. No automatic lease break or repeated mutation.

## Read-only baseline

- Existing publisher: Reader on the dedicated registry plus Repository Writer
  conditioned to `image-library` and `image-library-buildcache`; no app access.
- Existing deploy identity: Website Contributor on `pp-image-library`, plus Blob
  Data Contributor on only `release-control` and `rollback-backups` containers.
  Its GitHub environment still admits only the retired pilot branch. The role
  permits non-cooperating app writes; the blob lease cannot fence ARM.
- SCM and release storage deny by default and allow only the operator address.
  Storage shared-key authentication/public blobs are disabled. No all-Azure or
  GitHub-wide allowlist will be introduced.
- One legacy repository secret named `AZURE_CREDENTIALS` exists. Its value was
  not read. Retired workflow stubs do not revoke old secrets or Azure grants.
- Production remains the accepted v2.0.0 `2ffc0ff` / `40019125172-1`; the minimum
  24-hour observation cannot close before October 24 at approximately 14:08 PDT
  and requires actual telemetry, not just elapsed time.

## Skill routing

The generic prepare/validate/deploy recipe requires azd preparation, while this
repository uses an approved custom App Service container/ARM release protocol.
The Python-specific skill is a source/ZIP recipe, not this runtime. Do not add
azd, Oryx, a new runtime/plan or call this recipe `Validated` to satisfy tooling.
Use existing runbook gates and targeted resource/storage/RBAC verification.

## Status

PR #5 merged as `8605ecd` after container and T1/dependency checks passed.
Production builder ID `394835659`, source SHA-256
`5b41c586ba6c601562bdee1b1cb2f89eb81211928fa01d0d5fc55ff5738194d4` are pinned.
The existing publisher environment policy `64050289` now admits only `main`,
not the retired pilot branch. No Azure role expansion or production mutation.

The user also explicitly approved a temporary network-restricted rehearsal app
on the existing dedicated P2v3 plan, with synthetic data and no production
provider credentials. Stop that app after testing. Do not alter staging state.

Fresh production candidate build `40064558508-1` / `ba61c52` passed 647 target
tests, 14 browser/workflow checks, strict dependency audit and exact-image
smoke/security/SBOM. Authenticated artifact `12549051390` passed digest/layout/
run identity verification. Candidate digest:
`sha256:f5ad233782189bf29457b52ee1394a04f0209640cf8672fc68c42690524f9c12`.
Builder enablement returned to `false`; no staging or production deployment.

Created `pp-image-library-rehearsal` on the existing dedicated P2v3 with a fresh
session secret, no production provider credentials, auth bypass/test mode/ingest
off, restricted main/SCM access and its own mount. Its system identity has only
repository-reader access to `image-library`. Created managed identity
`id-image-library-rehearsal` (client `d0ecb6f2-6f39-4ff3-84b5-289751a45edd`), with
Website Contributor on only that rehearsal app, Reader on the existing plan and
Blob Data Contributor on only new private `ci-rehearsal` container. The operator
also has blob access to that synthetic container. No production role expansion.

The rehearsal workflow is manual/main-only/opt-in and uses that separate
identity. It requires an operator-added single-runner network allowance, then
verifies actual lease contention, protected synthetic-state readback, actual
forward/reverse digest updates, persistent drain/mount/fresh boot, exact resume
and stale-boot denial. Cleanup is ETag-conditional and only removes its own three
rehearsal files; protected owner/backup records remain private. Unknown outcomes
retain the lease and stop. The actual production promotion controller, real
catalog/SSO, stable unattended network and the broader fault matrix remain
separate evidence requirements; do not claim this subset closes those gates.

## Isolated CI rehearsal checkpoint — October 23, 22:19 PDT

PR #6 merged as `a9c1f48` after 670 target-Linux tests, 15 browser/workflow
checks, exact-image smoke/security and the independent dependency audit passed.
The rehearsal workflow ID is `394841917`; its environment admits only `main`.
The retired pilot deployment environment now admits only the non-existing
`retired/image-library-no-deploy` branch. The legacy `AZURE_CREDENTIALS` secret
has not been read or revoked; credential/writer inventory is not complete.

**Rehearsal run [40065382842-1](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/40065382842)
stopped and did not pass.** The dedicated CI identity reached restricted SCM,
ARM and synthetic blob storage. Execution reached the runtime resume request
after actual lease contention, protected synthetic backup, a forward immutable
image update, candidate readiness and configuration/state checks. No matching
runtime acknowledgement arrived; `response.json` was absent at reconciliation.
Do not claim stale-boot denial, exact resume, rollback or cleanup acceptance.
Sanitized failure artifact `12549212350` was independently verified against its
run/head identity, ZIP layout and digest
`sha256:b0ad7789dceb8c2948ebde78b4ec40b69ae68e2ef4072537b01264706d01f43b`.

Independent post-run checks confirmed the candidate image is still configured,
the synthetic fixture is unchanged, configuration matches its private backup,
and the persistent drain marker remains present. The rehearsal app was then
stopped and read back as **Stopped**. It was not rolled back or restarted.
The infinite lease on `ci-rehearsal/rehearsal.json` remains **locked**;
protected owner/backup records are under private prefix
`351d2dc4ae084e5c9df9737bb1eaf703/`. Never print the owner lease ID or private
configuration. Synthetic fixture/request state is retained for reconciliation.
Do not rerun the workflow, auto-break the lease, delete evidence or replay resume.

Temporary rule `rehearsal-ci-40065382842` was removed from both app and SCM,
and runner address `20.51.199.49` was removed from release storage. Independent
readback verified default Deny, operator-only access and storage bypass None.
Both production-builder and rehearsal enablement flags are `false`; pilot mode
remains `hold`. No production/staging ingress, settings, state or image changed.

At `2026-10-24T05:19:39Z`, the four public production checks passed for accepted
build `40019125172-1`: health/readiness/version HTTP 200 and anonymous admin 401.
This is not authenticated catalog, upload, performance or 24-hour telemetry proof.

Remaining: diagnose the missing runtime acknowledgement and reconcile the held
synthetic lease before a fresh attempt; complete rollback/cleanup and the broader
production-controller fault matrix; prove production CI identity/network access
and finish writer containment; review the real 24-hour telemetry window; then
obtain separate supervised-release and unattended-activation approvals. The
earliest observation checkpoint remains October 24 at approximately 14:08 PDT.
