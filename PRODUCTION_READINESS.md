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
