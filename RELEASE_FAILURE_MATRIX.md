# Release cleanup, write resumption and failure matrix

Local implementation checkpoint, October 24, 2026 UTC. No Azure mutations,
deployment, commit, push, new CI run or infrastructure activation in this work.

## Implemented contract

The controller explicitly calls `finalize_held` before recording successful
forward-release or rollback acceptance. The lease context refuses to release
unless finalization completed. Failed or interrupted work retains the lease;
it does not run cleanup in a `finally` block.

For each touched slot, staging first and production second:

1. Validate receipt, protected configuration and stable state. Production must
   still have its frozen snapshot, mount sentinel and persistent drain.
2. Stop once and confirm both ARM Stopped and named-container termination.
3. Recheck state/configuration; delete only owned nonce files with ETag
   conditions and verify their absence. Never delete another run's files.
4. Recheck state/configuration; start the same image once. Poll only bounded
   readiness GETs, requiring exact commit/build/version and telemetry.
5. Require one fresh named runtime, unchanged state/configuration, enforced
   public authentication and absent control files. Seal legacy RPC/image
   mutation after cleanup; only the one-shot post-cleanup protocol is permitted.

Any uncertain delete, stop, start, readiness or validation result aborts the
sequence. No retry of mutations, automatic state restore or cleanup replay.
When `resume_writes=True` is explicitly requested and the existing runtime
enablement is true, cleanup is followed by fresh authenticated process/read
verification. The new boot must differ from the pre-cleanup boot while mount,
build, nonroot identity, single worker, drain and frozen state still match.
Resume binds to that exact new build/boot/mount, not the old process.

Protocol 2 durably retires the exact request before acting and acknowledges its
retirement. The controller verifies request absence, conditionally deletes the
owned response and verifies an empty channel without restarting. A crash after
retirement cannot replay that request on a new process. Lost acknowledgements
remain ambiguous: retain the lease, never send resume again or restore old state.
After resume, verify the current process/auth/read behavior and configuration,
but never compare or restore frozen application files: real writes may have
begun. The lease cannot release on an incomplete/uncertain resume.

Protocol 1 remains compatible with prior runtime images for held releases.
The previously published candidate cannot perform protocol 2; a new reviewed
build is required. There is no automatic fallback to legacy resume. No runtime
enablement setting was changed by this implementation.

## Defined local matrix

| Area | Evidence / expected behavior |
| --- | --- |
| All 76 cleanup boundaries | Both provider-error and interruption injection; stop exactly at fault, retain lease, reject replay |
| All 19 forward-controller boundaries | Error/interruption injection; no subsequent adapter operation or duplicate update |
| All 26 confirmed-failure/rollback boundaries | Error/interruption injection; at most one rollback; no further mutation after fault |
| Named lifecycle | Missing/ambiguous history, target mismatch, lease loss and unconfirmed termination prevent start/update |
| ARM updates | Unknown PUT, asynchronous missing/foreign receipts, failed/canceled/unknown polling, deadlines and Retry-After fail closed |
| Cold readiness | Authentication/redirect/unclassified failures stop; only bounded GET retries for 502/503, network timeouts or a not-yet-matching build |
| Cleanup ownership | Foreign nonce, absent ETag, malformed/non-object content prevent deletion |
| Cleanup drift | State or configuration change after stopping prevents deletion/restart in either slot |
| Restart acceptance | Zero, overlapping or old runtimes fail; legacy RPC/image mutation is refused after cleanup |
| Controller outcome | Cleanup failure prevents success journaling and does not enter another rollback |
| Lease transport | Existing transport suite covers exact host/resource scope, contention, non-overwrite initialization, unknown writes and retained leases |
| Writable policy | Existing explicit option and runtime flag required; disabled configuration fails before lease/drain |
| One-shot runtime | Retirement/fsync failure prevents resume; stale boot stays drained; lost response after resume cannot replay on restart |
| All 18 resume/verification SCM boundaries | Errors and interruptions injected both before and after each operation; uncertain writes never cause another resume |
| Real channel/adapter integration | Temporary filesystem transport exercises post-cleanup probe, exact new-boot resume, post-write verification and empty channel; old runtime without protocol support fails without fallback |

Tests: `tests/test_production_cleanup.py`, `tests/test_production_lifecycle.py`,
`tests/test_production_azure_adapter.py`, `tests/test_production_release.py`, and
`tests/test_release_azure_io.py`, `tests/test_post_cleanup_resume.py` and
`tests/test_release_channel.py`. Boundary-count assertions make added controller
steps visible to the matrix. Synthetic failures do not simulate every Azure
platform behavior; this is complete coverage of the defined local boundary
matrix, not a claim of exhaustive distributed-system or live Azure testing.

## Acceptance boundary

Verification: fresh pinned Linux/amd64 Docker test stage passed **1062 tests**
with 10 existing UTC deprecation warnings (17.79 seconds). The 15 JavaScript
tests, workflow actionlint and `git diff --check` also passed. Test image config:
`sha256:6539785840f398a2e0f78555ce1b2f97f5f5a5522998a34ba42830712941b873`.
Command: `docker buildx build --platform linux/amd64 --target test --no-cache-filter test --load --tag image-library:resume-validation-tests .`.
No fresh release image, security scan or published CI receipt is implied.

The source changes remain local and must be reviewed and CI-validated before
release use. The updated adapter has not been exercised against live Azure.
The prior isolated rehearsal is evidence for the older harness, not this exact
orchestrator. Candidate staging comparison and representative performance
acceptance remain pending. Production promotion, write resumption, ingestion,
maintenance schedules and private-runner activation remain separate gates.
