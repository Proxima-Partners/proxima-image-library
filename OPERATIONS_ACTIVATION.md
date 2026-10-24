# Unattended operations: implementation handoff and activation gates

Updated 2026-10-23 (PDT). **Implementation and reviewed main integration complete;
not deployed or enabled for production releases.**
[PR #4](https://github.com/Proxima-Partners/proxima-image-library/pull/4) merged
reviewed head `57bd4f1` as `21a66fd`. Fresh PR checks passed 633 target-runtime
tests, 13 browser/workflow checks, all smoke/security gates and the independent
633-test T1/dependency audit. The CI Node 20 warning is resolved. See
`MAIN_INTEGRATION.md` and `UNATTENDED_IMPLEMENTATION.md` for evidence. Production
is still the accepted v2.0.0 build `40019125172-1` / `2ffc0ff`; no deployment,
Azure access change, new catalog write test or schedule activation is included.

Subsequent approved readiness work added the reviewed production builder and a
separate isolated rehearsal identity/app; see `PRODUCTION_READINESS.md`. The
builder passed and published candidate `40064558508-1`. Rehearsal `40065382842-1`
stopped on a missing resume acknowledgement and has not passed. Its app is
Stopped, temporary CI access removed, and synthetic recovery lease retained.
Production remains unchanged; activation is still prohibited pending the gates
below. Earlier statements about the PR #4 scope describe that implementation,
not the subsequently approved isolated resource provisioning.

## What the integrated implementation provides

- Visibility/auth-aware badge polling, one request at a time. Catalog refreshes
  are coalesced, copies are isolated, and in-flight data invalidated by a write
  is discarded. Thread-owned pooled Graph GETs have one bounded transient retry;
  writes are never replayed. One synchronous worker/one instance remains required.
- Report-only catalog diagnostics: serial, explicit scoped token, no dotenv/app
  credentials, no mutation methods. Maximum 300 seconds, 1,000 records, 40 pages,
  120 requests, 3,000 image files, 100 folders per tree and 20 thumbnail samples.
  Response/aggregate byte limits and a process alarm bound execution. Incomplete
  inventory never produces authoritative missing/orphan counts. No live catalog
  scan was run during this implementation.
- Authenticated exact GitHub run/attempt/artifact verification. Checks the reviewed
  workflow source hash, repository identity, successful build steps, ZIP digest,
  image manifest/config, security policy, scan, SBOM and runtime smoke evidence.
  ZIP contents remain in memory, not extracted or executed. GitHub tokens never
  follow signed storage redirects. Run/artifact identity is rechecked after fetch.
- Bounded ARM operation polling, including status and Location receipts and
  provider Retry-After intervals. Missing/uncertain results stop without blind
  retry/rollback. Polling follows the [ARM asynchronous operation contract](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/async-operations);
  exact Azure resource behavior and CI access still require live rehearsal.
- Write resumption defaults OFF. It needs both `promote(..., resume_writes=True)`
  and separately approved `PRODUCTION_RELEASE_RESUME_ENABLED=true`, exact
  commit/build/boot/mount, production slot, one actual worker, ingestion off and
  an idle drained process. A failed/ambiguous resume never enters auto-rollback.
  Confirmed rollback remains drained. No deployment CLI is exposed.
- Manual-only, default-branch-only, opt-in read workflows:
  `operations-health.yml` and `release-evidence-review.yml`. No Azure/OIDC/write
  credentials, cron, publish step or deployment command. Both remain inert:
  their explicit repository enablement variables are absent.
- The three obsolete deployment workflows are credential-free refusal stubs
  **on main**. Historical source/evidence remain in Git and GitHub. This
  does not revoke old credentials, disable older branch refs, or fence manual
  Azure callers. Keep pilot mode `hold` and the legacy workflow disabled.

## Evidence gathered without changing production

- Exact accepted artifact `12529602290`, run `40019125172`, attempt `1`, verified
  through authenticated GitHub reads. Archive digest:
  `sha256:41ca5f92a9d63e9bb36fcebd8cc76df480f17e13b46350c2062273058409a67b`.
  This is verification of the existing artifact, not a fresh vulnerability scan.
- At 2026-10-23 22:05 UTC, four anonymous custom-domain checks passed: health,
  readiness with telemetry enabled, exact version/build and admin HTTP 401.
  No authenticated sign-in, catalog, upload, Azure config or 24-hour telemetry
  claim follows from that point-in-time report.
- `UNATTENDED_IMPLEMENTATION.md` records regression results and build-only CI.
  The offline runtime fixture checks persistent drain across restart, fresh boot,
  opt-in exact-boot resume, stale-boot rejection, nonroot identity, and actual
  serving of the new browser polling asset. No real provider credentials/data.

## Activation sequence: separate approvals required

1. **Completed:** implementation review and full container-era integration into
   legacy main through PR #4, with all three checks passing. Main-merge approval
   did not authorize deployment. Preserve the accepted immutable rollback artifact
   and private backups. Do not dispatch or rerun the retired pilot.
2. Complete the post-cutover observation using real production-slot telemetry,
   including dependencies, 5xx, deliberate 401/404 exclusions, upload-processing
   spans and browser timings under representative use. The earliest 24-hour
   checkpoint is approximately October 24 at 14:08 PDT; elapsed time alone is
   not evidence. No continuous monitor was created by this branch.
3. **Builder completed:** reviewed manual-main-only publisher, exact source/ID
   receipt policy and candidate `40064558508-1` passed. Its enablement flag is
   back to false. Candidate publication does not authorize deployment; retain
   exact-image evidence and later promote the same digest staging -> in-place
   production under the separately approved release procedure.
4. Scoped access/rehearsal work is approved but incomplete: prove ARM polling,
   staging/production SCM and private release storage access with that identity.
   Inventory old secrets, OIDC subjects, branch/environment rules and manual
   operators; contain every writer. The blob lease serializes cooperating
   clients but does **not** fence ARM. Never auto-break an uncertain lease.
5. Rehearse isolated recovery with protected synthetic state: lease contention
   and loss, acknowledged failure, unknown PUT outcome, interrupted polling,
   concurrent config/files, expired receipts, restart/drain, exactly one rollback,
   denied resume, and ambiguous resume. Verify cleanup and protected journals.
   Do not substitute unit tests or the earlier cutover for this CI-path rehearsal.
6. Approve the first supervised normal container release. Verify exact staging
   artifact, auth/bounded reads, lease/drain/zero work, protected backup, unchanged
   configuration/files, in-place digest, fresh boot and custom-domain behavior.
   Review any writable acceptance scope separately; the previous disposable
   canary approval was consumed and is not reusable.
7. Only then approve unattended promotion/write-resumption and read-only
   operations activation. Any ambiguous write outcome stops, retains evidence
   and requires reconciliation. Never rerun a deployed workflow to recover it.

## Read-only maintenance operating proposal (not scheduled)

| Procedure | Proposed cadence after approval | Bounds and escalation |
| --- | --- | --- |
| Public contract | Every 15 minutes | Four anonymous GETs, 30s total, no retries/redirects, 32 KiB/response. Any failure/incomplete result alerts; it is not a full app-health verdict. |
| Application telemetry review | Daily and after releases | Production build/slot only; compare request/dependency failures, processing p50/p95, throttles and representative browser timings. Do not use SSE connection duration as job time. |
| Catalog integrity report | Daily outside active work | Separate least-privilege read identity; existing bounded scanner. Incomplete/unknown stays explicit; findings become reviewed work, never repairs. |
| Image security inventory | Daily and before promotion | Rescan retained exact digest with a current database; retain raw results/SBOM. New HIGH/CRITICAL or expired review stops promotion. No automatic exception extensions. |
| Dependency/base-image proposals | Weekly; urgent security findings sooner | Small reviewed update batches, locked dependencies and pinned base digests, full target-runtime tests/security/smoke, no auto-merge/deploy. |
| Backup and recovery evidence | Every release; monthly isolated rehearsal | Protected exact-state backups/readback. Never restore automatically over newer writes. No retention deletion without reviewed scope. |
| TLS expiry/renewal | Daily expiry check; alerts at 30/14/7 days | Certificate currently recorded to expire 2027-04-18; verify live before relying on it. Renewal and private-key access require a dedicated procedure/approval. |

Schedule activation needs an accountable owner, actual notification destination,
tested failure notification, missed-run detection, retention and a disable switch.
GitHub cron only runs from the default branch and may be delayed or dropped;
it is not a precise uptime monitor. See [GitHub scheduled-event limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
No alert destination, monitor, cron, credential or dependency bot was configured.

## Safe commands and release hold

Local verification (isolated fixtures):

```sh
docker buildx build --platform linux/amd64 --target test --no-cache-filter test --load --tag image-library:unattended-tests .
node --test tests/js/*.test.cjs
```

Read-only entry points are `python -m scripts.operations_health`,
`python -m scripts.library_health_check` and `python -m scripts.release_artifacts`.
Use `--help` for arguments. The first two refuse network work unless explicitly
enabled; the catalog checker also needs a scoped diagnostic token. Do not copy
production settings or export browser sessions to make these run.

No increased tier, scale-out, threaded Gunicorn, ingestion restart, backfill,
delete/repair, DNS change, legacy restart/retirement or Pete/shared-plan change
is authorized by this implementation. Do not claim a measured user-speed gain
until the new build passes representative production acceptance.
