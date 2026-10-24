# Production builder, CI access and recovery readiness

Approved 2026-10-23 PDT following the completed main integration. This approval
covers a new reviewed production builder, narrowly scoped CI access and isolated
recovery rehearsal. It does not activate production promotion, write resumption,
ingestion, schedules, a new catalog canary or legacy deletion.

**Current checkpoint, October 24 UTC:** new immutable build `40070894451-1`
passed isolated rehearsal and supervised read-only staging rollback/forward
validation. Production remains unchanged. The initial staging readiness pause
was reconciled without mutation replay, and the retained lease was released
after verified completion. Functional reads match; performance improvement is
not demonstrated, so promotion remains on hold. See `CANDIDATE_VALIDATION.md`.
Earlier checkpoints below are historical, not the current candidate status.

**Latest checkpoint, October 23 22:55 PDT:** fresh isolated CI recovery
`40067583967-1` passed and was independently verified. Rehearsal is Stopped on
the prior image, owned files absent, lease unlocked and temporary network access
removed. Production remains unchanged. Earlier failed-run sections below are
historical; see the final acceptance section for the current state and limits.

**Performance validation, October 23 23:15 PDT:** fresh tests/audit and release
provenance checks passed; authenticated current-production baseline reads were
measured. The candidate remains undeployed, and the production-controller cold
lifecycle/full fault matrix and remaining acceptance gates are still open.
See `PERFORMANCE_RELEASE_VALIDATION.md`; this does not authorize deployment or
close the production-readiness gate.

## Execution plan

Local follow-up: the stopped-cleanup orchestration and defined controller
failure-injection matrix are implemented; see `RELEASE_FAILURE_MATRIX.md` for
the precise scope. This closes the local implementation gap, not the exact-code
CI/live-rehearsal or staging-performance gates. Post-cleanup write resumption is
now locally implemented and tested using fresh-boot verification and durable
one-shot RPC; it still requires the existing explicit option/runtime enablement.
A new runtime candidate is required. No live settings were changed.

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

## Operator reconciliation — October 23, 22:34 PDT

The previous held rehearsal is now reconciled, **not reclassified as a CI pass**.
Azure Resource Health reported Available. The diagnostics skill's names-only
collector was used; its deployment-list command was unavailable in this CLI, so
targeted ARM and bounded platform/SCM log reads supplied the lifecycle evidence.
Logs show the old runtime continued until `05:15:17Z`, after the candidate became
ready at `05:14:57Z`. Thus a single App Service instance/one Gunicorn child does
not establish one runtime during an online update. The shared response vanished
during that overlap; overlap is a supported contributing hypothesis, not proof
of the exact filesystem failure mechanism.

The failed request and configuration were preserved in private storage under the
existing recovery prefix before status-only diagnosis. Early diagnostic starts
were contained/stopped when the readiness helper rejected the stopped-site
response or timed out; no status/resume was replayed. The helper now polls
transient startup responses/GET timeouts within a fixed deadline and permits
stopped-site HTTP 403 only in an explicit cold-start path. After a controlled
restart, three fresh status acknowledgements passed with drain/state preserved.

A separate, fresh operator acceptance then passed stale-boot rejection, exact
resume and re-drain. Candidate termination was verified from named platform
lifecycle records before one stopped-image rollback. The prior build became
ready with a fresh boot and unchanged mount, configuration and synthetic state.
The app was stopped and its runtime termination confirmed before ETag-conditional
deletion of only its synthetic counter, request and response files. Each read
back HTTP 404. Owner/configuration/recovery records remain protected and retained.
The existing lease was explicitly released, never broken.

Independent readback verified prior digest `1a1d24e…`, **Stopped**, zero active
rehearsal containers, unchanged configuration and **unlocked** synthetic lease.
Public production checks at `2026-10-24T05:34:07Z` passed on the original accepted
build. Production/staging images, settings, ingress, state and provider data are
unchanged. No temporary runner access was added during operator reconciliation.

The revised isolated CI harness now stops and verifies runtime termination before
each digest change, checks authenticated SCM/storage access before starting, and
stops before channel cleanup. Readiness polling and sanitized phase/error reporting
are improved. Local checks passed 680 tests with seven Linux-only skips, 15 JS
checks, actionlint and diff validation. A fresh reviewed CI rehearsal is still
required. The production adapter's lifecycle policy/full fault matrix, production
CI access, 24-hour telemetry, supervised release and activation remain open gates.

PR #7 merged as `4c5ca05` after 688 target-Linux tests, 15 JS checks and both
container/security and dependency gates passed. Fresh CI run `40067116549-1`
verified the OIDC/network path but stopped before lease acquisition or app start:
reinitializing the existing lock returned HTTP 409 `BlobAlreadyExists`, whereas
the old helper expected 412. A bounded conditional-create diagnostic independently
confirmed that exact error and unchanged lock bytes/ETag; the lease stayed unlocked.
The only new private object is unused owner record prefix
`3364bd8ce97b424a968766c5277c9a1f/`, retained for audit. The app remained Stopped.
Temporary rule `rehearsal-ci-40067116549` / runner `52.183.219.35` was removed
from main/SCM/storage, and rehearsal enablement returned to false.

The corrected helper first HEAD-checks a BlockBlob and reuses it without a write;
only an absent blob is conditionally created. A creation race accepts only the
specific `BlobAlreadyExists` conflict with independent HEAD verification, never
a generic 409, overwrite, mutation retry or lease break. Target preflight, lease
initialization and acquisition now have separate sanitized report phases. Focused
checks passed 101 tests; a live existing-lock check performed no PUT/acquisition.

PR #8 merged as `f9a72e9` after 693 target-Linux tests, 15 JS checks, exact-image
smoke/security/SBOM and the independent dependency audit passed. The container
and T1 runs are `40067445599` and `40067445656`. Local verification passed 686
tests with seven Linux-only skips and ten existing UTC deprecation warnings.
Fresh isolated run `40067583967-1` uses that reviewed main commit; its network
artifact `12550226053` was independently authenticated and digest-verified before
temporary access was added. The failed earlier runs remain failed historical
evidence; neither was rerun or relabeled successful.

## Fresh isolated CI acceptance — October 23, 22:55 PDT

[Run 40067583967-1](https://github.com/Proxima-Partners/proxima-image-library/actions/runs/40067583967/job/120793962597)
passed from reviewed main `f9a72e92e9b23f5b72d456e3aa5abffddd1081bf`.
Authenticated artifact `12550296111`, 586 bytes, passed run/head/workflow/attempt,
ZIP layout and SHA-256 verification:
`870699eb34f49de0a3d46617be7a90e09e7eb9a1b5599ba70873f56d26b70cf1`.

- Real CI OIDC, restricted SCM/storage access and competing-lease rejection passed.
- Protected synthetic backup/readback, stopped-image forward deployment, fresh
  boot and persistent mount/drain/configuration checks passed.
- Stale-boot resume was denied; exact resume and subsequent re-drain passed.
- One stopped-image rollback restored the prior build with fresh boot and
  unchanged synthetic state/configuration. Both image updates returned HTTP 200
  without an asynchronous receipt: this run does **not** prove live async polling.
- Named runtime termination was verified before image changes and final cleanup.
  Only the owned synthetic counter/request/response were deleted, conditionally
  by ETag, with HTTP 404 readback. No existing application data was deleted.
- Independent operator reads verified Stopped, prior digest `1a1d24e…`, zero
  active containers, unchanged configuration, three absent owned files and an
  unlocked lease. Private owner/backup records under
  `ci-rehearsal/64927760a57743ec90b912c5927614fb/` remain retained.
- Temporary rule `rehearsal-ci-40067583967` and runner `135.119.39.215` were
  removed from app/SCM/storage. Readback verified operator-only/default Deny,
  storage bypass None, shared keys disabled and the existing Defender scanner
  exception preserved. Both builder/rehearsal flags are false; pilot stays hold.

The job took 7m32s, including 3m44s awaiting scoped operator network access;
the actual recovery step took 3m30s. This is synthetic release/recovery timing,
not a production deployment SLA or evidence of faster catalog/upload behavior.
Public production checks at `2026-10-24T05:55:36Z` passed on accepted build
`40019125172-1`. No production/staging release, provider credentials, catalog
canary, ingestion, schedule, DNS, tier or Pete/shared-plan changes occurred.

## Remaining gates and next decision

**User decision, 2026-10-23:** defer the dedicated private CI network and managed
paid runner until the performance release is validated. This infrastructure is
not a prerequisite for the supervised performance release. Implementation and
testing may continue unattended within their existing scope; production releases
remain supervised, with restrictive access and the existing safety gates intact.
Validation is a trigger to reconsider the proposal, not authorization to provision.

1. Carry the verified cold-lifecycle policy into the production adapter and
   complete the full production-controller fault matrix in isolation. Include
   lease loss, unknown writes, interrupted/async polling and ambiguous resume;
   never substitute the happy-path subset above for those proofs.
2. Prove the actual production identity/SCM/storage path using controlled,
   operator-scoped access and finish credential/manual-writer containment.
   Retain supervised per-run network setup and verified cleanup; do not widen
   access or provision private-runner infrastructure to remove that intervention.
3. Review real production telemetry for the complete observation window, earliest
   October 24 approximately 14:08 PDT. Elapsed time/public probes are insufficient.
4. Obtain the separate supervised-release approval, promote the exact reviewed
   digest through staging and in-place production, and measure representative
   performance/auth behavior. Any new disposable write canary needs new scope.
5. Only after performance acceptance, reconsider and separately approve a stable
   unattended release network. Prove it before approving unattended promotion/
   write resumption. Maintenance activation also needs separate approval, tested
   alerts, an owner and a disable switch.

Signing follow-up: both implementation head `6921e32` and checkpoint `0a64d5b`
contain SSH signatures, but GitHub reports `verified=false`, `reason=unknown_key`.
Local signature verification also lacks an allowed-signers file. The authenticated
run/artifact checks above are separate evidence, not a claim of GitHub-verified
commit signatures. Registering account signing keys or changing local trust
configuration requires a separately reviewed scope; neither was changed here.

Deferred infrastructure option, to revisit after performance validation: a
repository-restricted, GitHub-managed
Ubuntu larger runner using a dedicated Azure private network in West US 2.
The organization currently has GitHub Team, and GitHub documents support for
Team/private networking, that region, and larger runners (not standard runners).
Keep build-only jobs separate from the one-at-a-time release runner. This needs
new Azure network resources and paid runner configuration, so it is a proposal,
not provisioned or authorized by the isolated-app approval. Scope/cost review
must precede provisioning; deny inbound traffic, constrain outbound access and
prove rehearsal-only connectivity first. Do not grant production access as part
of that initial network proof. See [GitHub private networking](https://docs.github.com/en/organizations/managing-organization-settings/about-azure-private-networking-for-github-hosted-runners-in-your-organization)
and [current configuration requirements](https://docs.github.com/en/organizations/managing-organization-settings/configuring-private-networking-for-github-hosted-runners-in-your-organization).
