# Production release runbook and remaining automation gates

Updated 2026-10-23 (PDT). Scope: accepted supervised production cutover, followed
by approved implementation and main integration; no unattended production promotion.

Implementation update: PR #4 integrated `perf/unattended-operations` into main
as `21a66fd` after all three CI checks passed. It adds read efficiency,
authenticated artifact verification, conservative ARM polling and disabled
operations workflows. This new implementation is **not deployed or activated**.
Subsequent readiness work completed a reviewed production candidate builder.
The separate isolated Azure rehearsal stopped at a missing resume acknowledgement;
its app is Stopped, temporary runner access removed, and synthetic recovery lease
held. Do not replay that run or break its lease. See `PRODUCTION_READINESS.md`.
Current implementation and remaining acceptance gates are in `UNATTENDED_IMPLEMENTATION.md` and
`OPERATIONS_ACTIVATION.md`; older preparation sections below are historical.

## Accepted production checkpoint

**Production cutover and the single disposable write canary PASSED.** The public
custom domain serves writable v2.0.0 / `2ffc0ff` / `40019125172-1`, exact image
`sha256:1a1d24ede2eb7bfd81cb1ea2b11ea5518f0df5c4441dd714f2ef49ab5e1afa9a`.
See `cutover-evidence/2026-10-23-production-cutover.json` for the sanitized report.

- Legacy `PP-App-Serv` production and staging are **Stopped**. Do not restart
  either while the new app can write. Do not stop/resize the shared S1 plan or Pete.
- New production is writable; new staging is read-only. Both ingestion pollers
  remain disabled. Normal manual uploads work; watched-folder ingestion does not
  resume automatically. Scheduled maintenance remains disabled.
- `library` CNAME now points to `pp-image-library.azurewebsites.net`, TTL 300;
  all four authoritative servers and the operator resolver verified it. TXT and
  `www.library` records and the old certificate binding are intact. New main app
  ingress is open behind application authentication; SCM remains independently
  operator-only/default Deny. Staging stays operator-only.
- Final private backups use `pilrelease9528/rollback-backups/9946fbe74da346bebac8e725316ff4ff/`.
  They include the stopped legacy config/state/Git source, prepared target,
  280-record baseline and the verified disposable-canary ownership manifest.
  `accepted-production.json.gz` preserves the verified writable configuration and
  state. Exact readback passed; the final release lease was explicitly released
  and independently verified **available/unlocked**. The owner recovery record is
  retained locally; it is not permission to reacquire or replay that operation.
  No private settings, file contents or integrity hashes belong in Git/CI logs.
- Exactly 806 bytes in two state entries were installed into empty target roots
  with exclusive isolated restore and per-root no-overwrite rename. Source state
  and target state still match exactly after the canary. The transfer payload was
  removed; the installation journal is retained. No credential file, staging
  history, quota reset or staged-upload replay was involved.
- Fresh Microsoft callbacks, authenticated admin status, 280 records, 20 loaded
  thumbnails, original-secret signed MCP JPEG delivery and invalid-auth rejection
  passed on the real custom domain. One actual UID/GID 65532 worker is verified.
- The 1800×1100 disposable PNG produced exact original bytes, 1600×978 WebP/PNG,
  a 240×147 JPEG thumbnail and a matching metadata sidecar. Its one new record
  (`507`) and four owned files were removed through ETag-conditional Graph calls;
  each was verified absent. All original 280 record IDs/fields remain unchanged.
  Normal DriveItem deletion moves files to the recycle bin; no purge was used.
  [Microsoft Graph deletion semantics](https://learn.microsoft.com/en-us/graph/api/driveitem-delete?view=graph-rest-1.0).
- Telemetry confirms the production slot/build, successful callbacks and upload.
  The observed window has zero dependency failures/5xx responses, five deliberate
  401 tests and one unmatched 404 whose path is intentionally not recorded.
  Do not report zero request failures. The 15-second small-fixture upload is not
  a workload benchmark; its processing span was 14.922 seconds, versus 4.252 seconds
  for AI and 0.334 seconds for derivatives. SSE HTTP span duration is not job time.

### Operating boundaries after cutover

Keep `IMAGE_LIBRARY_PILOT_MODE=hold` and the legacy workflow disabled. The old
read-only pilot workflow is not a writable-production release procedure. Do not
dispatch it against the now-live app. Remote `main` now contains the reviewed
implementation and retired deployment stubs. The new container-only production
builder and trusted policy are complete; production activation remains separate
reviewed work. See `PRODUCTION_READINESS.md`. No slot swaps, automatic undrain or automatic
state restore.

The 24-hour observation gate remains open; no continuous monitor was created.
Retain old apps, settings, TLS binding and backups at least through **2026-10-30**;
deletion is a separate approval. Resume watched-folder ingestion only after
explicit approval and verification of a single active owner. Finish trusted CI
receipt retrieval, shared lease participation, runner storage/SCM network and
role access, and supervised recovery before enabling unattended promotion.

Initial-cutover rollback now requires checking for **new writes** first. Stop or
drain the new writer, capture and reconcile current local state and SharePoint
changes, then restore the old route/app only under the same exclusive lease.
Never overwrite new state with the old backup or reverse SharePoint writes.
At acceptance the disposable canary is cleaned and local state matches the old
snapshot, but that fact will become stale as soon as normal use resumes.

### Pre-cutover readiness (historical)

**Current checkpoint:** `2ffc0ff` / `40019125172-1` passed 487 target-Linux tests,
security/smoke gates and both immutable in-place deployments. Actual Azure worker
filesystem probes, bounded reads, original MCP-key compatibility, separate slot
telemetry, trusted custom-SNI TLS, read-only restart and stopped-target SCM recovery
passed. Production provider/MCP settings, upload/rate limits, CORS and custom
callback are preserved/prepared; staging retains its own credentials. SCM now
has explicit operator-only rules independent of main ingress, which is still
restricted. Both apps remain read-only/ingestion-off. No final state transfer,
DNS destination cutover or write canary has happened. The prior TTL window ends
20:55:10 UTC / 13:55:10 PDT. Completed preparation leases are released.
See `cutover-evidence/2026-10-23-readonly-cutover-readiness.json` and the exact
deployment report/receipts. Unattended production promotion is not enabled.

### Earlier candidate checkpoint (historical)

**Cutover and unattended production promotion remain NO-GO.** Candidate
`a15474c` / build `40016044994-1` passed 459 target-Linux tests, exact-image
smoke/security gates and both in-place read-only deployments. Its staging SCM
release channel proved one actual UID/GID 65532 worker and a bounded catalog read.
The newly approved Azure-aware state policy below requires a fresh candidate.
Legacy `azure-deploy.yml` is now
disabled, old staging is stopped, and only the library CNAME TTL changed from
3600 to 300 seconds; its destination remains the old app. Only staging's release
control/probe/telemetry flags changed. Provider/MCP credentials and catalog data
have not changed. Dedicated storage,
its scoped grants, target TLS and private backups are described below. Historical
findings in `PRODUCTION_CUTOVER_PREFLIGHT.md` must be refreshed before execution.

## Prepared locally

### Persistent provider credentials

`src/stock_credentials.py` owns the four stock providers' five allowlisted keys.
**Approved policy adjustment, 2026-10-23:** Azure credentials are environment-only.
Presence of `WEBSITE_INSTANCE_ID` enforces this, even with an explicit false flag;
`STOCK_CREDENTIALS_ENV_ONLY=true` also enables it outside Azure. Invalid flag
values fail closed. All providers are non-editable in Azure, including unset ones.
Any existing dedicated credential file, directory or link prevents startup; it
is never read, migrated, deleted or overwritten automatically. Keep credentials
in Azure application settings, not the shared state filesystem.

Only local/file-enabled installations parse `APP_STATE_DIR/proxima_stock_keys.env`,
without interpolation and independently of `PYTHON_DOTENV_DISABLED`. Local development
uses the same dedicated filename at the repo root; it is gitignored and excluded
from the Docker context. Arbitrary bundled/parent `.env` discovery was removed
from the app; the explicit project-root development file remains opt-out.

Policy:

- Environment-supplied keys, including intentionally empty values, win. If any
  key for a provider is environment-managed, that provider is read-only in the UI
  and its update API returns 409. Change those values in Azure, not in two stores.
- Local file-managed updates validate the entire request before any mutation, reject
  unknown/multiline/empty values, serialize within the single process, use a 0600
  temporary file, fsync and atomic replacement, then update process memory.
- A failed replacement leaves the previous file/environment intact. A failure
  after replacement is ambiguous: return 503 and reconcile/restart, never claim
  rollback or blindly retry. External file edits also require restart.
- A local credential file must be regular and not a symlink. Unknown/duplicate keys
  or malformed syntax fail closed. It is forbidden in Azure state transfers.
- Responses expose presence/source only, not secret fragments. Password inputs
  clear after save/cancel. Existing login, admin, CSRF and read-only controls remain.
- Unsplash download tracking now reads the current environment value instead of
  a class attribute captured before credential rotation.

This is a single-worker policy, not a distributed secrets manager. It does not
rotate or migrate any live credential. At cutover, prefer preserving the existing
Azure-managed provider settings; the UI will truthfully show them as read-only.

### Per-slot telemetry

Set the slot-local `TELEMETRY_SLOT` to exactly `production` or `staging` during an
approved configuration step. Missing/unknown values export `unknown`, never raw
hostnames or arbitrary labels. The explicit resource now distinguishes the same
build by slot in `service.instance.id`, `image_library.slot` and
`deployment.environment.name`. The existing Insights exporter/resource is reused;
no extra SDK, resource or telemetry destination was introduced. URL/identity/
prompt/exception filtering and bounded export remain intact.

The Application Insights instrumentation skill informed reuse of the existing
connection and exporter. Actual per-slot Azure ingestion is still a live gate;
unit tests and offline smoke tests do not prove telemetry delivery.

### Production release policy core — not yet a runnable deployment tool

`scripts/production_release.py` is an adapter-driven, locally fault-tested policy.
An Azure/SCM adapter draft now exists in `scripts/production_azure_adapter.py`;
there is still no CLI apply mode, production workflow or public authentication
bypass. Do not wire a fake adapter or supplied JSON observations to real mutation
commands. This is **locally tested preparation, not completed unattended
production automation**. Metadata matching is not trusted artifact retrieval.

The core enforces:

1. Exact new-app/dedicated-plan/slot identities; one instance and one worker;
   immutable approved-registry digest; current passing candidate/prior receipts.
2. An already validated read-only staging candidate, authenticated read checks,
   known prior writable production, and ingestion off. This is a normal future
   container update, not the initial source-app/DNS cutover.
3. An exclusive lease supplied by the adapter, durable exclusive journal,
   persistent drain, bounded wait for actual zero work, and a protected state
   checkpoint. Recheck staging, prior configuration, files and receipt expiry
   immediately before the update. Never change settings as part of promotion.
4. One acknowledged image update in place, no swap. Verify exact build/digest,
   fresh boot, nonroot identity, original mount and actual file integrity,
   authentication and functional reads while writes remain drained.
5. An ambiguous update, lost lease, changed configuration/files, or uncertain
   mount/boot stops without another mutation. Only a confirmed bounded failure
   can enter reconciliation and one prior-digest rollback. Verify that rollback;
   never restore older application files or reverse SharePoint writes.
6. Success and rollback both remain drained for supervised acceptance. Reusing a
   journal is rejected. No automatic undrain, credential change or ingestion.

Opt-in runtime support: `PRODUCTION_RELEASE_CONTROL_ENABLED=true` creates a
separate non-secret `.image-library-release-state` sentinel and returns its
identity/build only from the existing authenticated admin status endpoint.
It requires an absolute state directory, an explicit telemetry slot and the
pilot probe disabled. The pilot's read-only probe checks remain unchanged.
The sentinel proves mount identity, not backup completeness or data integrity.
Default behavior remains disabled; a new release sentinel was verified on staging
without changing its original pilot sentinel. Main has not yet enabled this channel.

### Approved storage and authenticated control preparation

- Deployment `image-library-release-storage-20261023` succeeded after ARM
  validation and a what-if containing exactly eight storage-only creates. The
  dedicated account is `pilrelease9528` in West US 2, Standard LRS/Hot.
- Containers `release-control` and `rollback-backups` disallow anonymous access.
  HTTPS-only/TLS 1.2, shared-key access off, OAuth default, versioning on and
  30-day blob/container soft deletion are verified. Firewall default is Deny,
  bypass None, with one operator IPv4 rule. This is **not** a private endpoint:
  its public endpoint exists behind the firewall. No Pete/Research store changed.
- Four new Blob Data Contributor assignments are scoped separately to the two
  containers for the existing Image Library release identity and operator. This
  does not remove inherited subscription-level administrative access. Operator
  OAuth data-plane reads passed. CI data-plane access has **not** been proven;
  its runner network path is not yet allowed by the operator-only firewall.
- `scripts/release_azure_io.py` uses the authenticated Azure CLI identity (OIDC
  when used by CI), exact allowed hosts, bounded responses and no redirect,
  proxy, password or storage-key fallback. Operator Entra bearer GETs to all
  four Image Library SCM VFS roots returned 200; no application files changed.
- Infinite blob leases retain an ambiguous/crashed release for reconciliation;
  there is no automatic lease break. The private 0600 recovery record is fsynced
  before acquisition. Live rehearsal on **only** `release-control/rehearsal.json`
  passed acquisition, competing-owner rejection (409), renewal, release and
  successor acquisition. Final server state is available/unlocked. The production
  lock was subsequently initialized and held for TLS preparation; it was released
  after explicit reconciliation (see below). Rehearsal blob/versions are retained.
- Blob leases protect the blob, **not ARM**. All deployment writers must honor
  the shared lock; old workflows/manual ARM writers are not yet integrated.
  Never describe this as platform-enforced ARM fencing. On ambiguity, keep the
  lease and apps drained; reconcile actual operations before manual release.
  See [Azure lease semantics](https://learn.microsoft.com/en-us/rest/api/storageservices/lease-blob).
- `src/release_channel.py` is an opt-in filesystem channel behind existing SCM
  publishing permission (not Linux file modes on `/home`). It accepts only fresh
  bounded status/probe/state_probe/drain-on
  requests, not undrain or arbitrary commands. Probe reads at most one record;
  returned metadata contains no record contents. Worker count comes from the
  actual Linux Gunicorn child process, not App Service instance count. Default
  public/admin authentication remains unchanged. Live staging status/catalog
  RPC passed; the new filesystem probe still needs deployment. It creates one
  exclusive nonce-named non-secret fixture, proves actual-worker write/read/rename,
  and deletes only that fixture. Failures preserve it for reconciliation.
- `scripts/release_state_archive.py` captures only six approved state roots,
  bounded to 64 MiB/1,000 entries, rejecting links/special files and unstable
  snapshots. It preserves bytes/modes/owners. The adapter verifies private
  compressed backup bytes after upload and checks mount identity independently.
  Actual private backups and isolated nonroot recovery are now verified below.
  `release_state_restore.py` validates the entire bundle. Default `strict_posix`
  restores into a new owner-only directory with UID/GID 65532 and 0600/0700 modes.
  Those local Linux tests do NOT establish Azure mount permission enforcement.
  Explicit `azure_shared` verifies observed UID/GID 65534 and 0777 metadata,
  without chmod/chown or owner-only claims. It forbids credential files and
  unresolved staged-upload children. Secrets stay in Azure settings/protected
  release storage; the shared mount relies on app isolation and SCM authorization.
  Azure's just-written file metadata proved transiently unstable in the synthetic
  rehearsal. Only read-only capture is retried (at most 12 attempts, 0.5s apart),
  requiring two consecutive identical internally stable captures. No mutation
  retry or weakened archive invariant is allowed. Persistent instability stops.
  Both policies verify exact bytes. The separate Linux `RENAME_NOREPLACE` primitive refuses
  any existing target state. Per-root publication is atomic, not a group
  transaction: an interrupted install keeps its fsynced journal and partial
  state for reconciliation, never automatically retries or rolls back. It still
  requires a held lease and both source/target applications stopped by the caller.

The Azure Storage skill informed deterministic identity use and container-scoped
access. This repository remains an existing Bicep/Azure CLI/GitHub Actions
deployment, not an azd project; no artificial azd validation status was created.

## Required implementation before any unattended production release

- Complete and rehearse the adapter using approved identity and exact resource
  scope. Verify the release identity's SCM permission and needed dedicated-plan
  read access; operator checks do not prove CI access. Do not repurpose the MCP shared key,
  persist browser cookies in CI, turn off CSRF, or bypass user authorization.
  Existing interactive admin authentication can serve a supervised rehearsal,
  but is not a durable unattended service identity.
- Integrate the approved lease/checkpoint store across CI and manual writers;
  check ownership inside every mutator. Establish a narrow CI network path and
  verify removal of any temporary access rules, without granting broad access.
  Keep the existing `image-library-deploy` GitHub concurrency group and
  `cancel-in-progress: false`. A runner-local file lock or run-list query alone
  cannot serialize all writers. Storage-only rehearsal is not release rehearsal.
- Verify receipt provenance from the reviewed commit/CI run and bind security,
  SBOM, runtime evidence and registry digest. The core validates shape/identity/
  expiry, not artifact signatures or GitHub provenance. The adapter currently
  matches supplied run metadata; an authenticated downloader binding all exact
  CI artifacts is still required. Its `VerifiedReceipt` wrapper is not an
  independent security boundary and must not be constructed from arbitrary JSON.
- Implement bounded ARM polling and authenticated status/read probes with no
  redirect-as-success behavior. Compare complete protected configuration only
  in memory; never log secrets or their hashes. Verify temporary ingress cleanup,
  if ever needed, in the adapter's finalization path.
- Implement protected backups and file manifests for the selected mutable paths,
  with ownership/mode checks and independently verified restore. Exclude only
  explicitly reviewed ephemeral files. Include persistent credentials in protected
  integrity comparisons without exposing their content/hashes in public reports.
- Rehearse acknowledged failure, uncertain Azure responses, lease loss,
  concurrent config/state edits, expiry, restart/drain persistence and one verified
  rollback on an isolated writable fixture. Then complete the first supervised
  public cutover and observe 24 hours before considering automatic undrain.

## Legacy containment and release hold

### Executed checkpoint, 2026-10-23

- Sole user confirmed no uploads/imports/previews/maintenance are running and
  will keep the app idle. Chosen method is an explicitly supervised app stop,
  not a drain bridge. Old revisions have no process-level active-work counters;
  empty ingest and saved job settings do not establish that evidence.
- `azure-deploy.yml` (workflow 256351732) is `disabled_manually`. No active or
  queued runs were present. Pilot mode remains `hold`; remote main is untouched.
- Preliminary backups for all four exact apps/slots include selected state,
  full private settings/web/auth/storage/identity/host bindings, target container
  configuration and exact Git source archives. Each upload used exclusive
  creation and exact readback. Both legacy bundles were restored privately on
  Linux as UID/GID 65532 with read/write/rename proof. No private content or
  state/credential hashes were put into GitHub artifacts or this report.
- Backup prefix `50db4826509344c9af9fbd9326cf19cd` in the dedicated
  `rollback-backups` container: legacy main 2 entries/806 bytes; legacy staging
  3 entries/7680 bytes; both new targets have zero allowlisted state entries.
  These are running-app checkpoints, not the final production transfer snapshot.
  Git source archives are not byte-for-byte Oryx dependency/deployment artifacts;
  keep the existing legacy app/files intact as the primary rollback runtime.
- Both old saved schedules are disabled, saved approvals/checkpoints are empty,
  and staged-upload directories contain no files. Separate audit histories
  contain 1 and 21 entries. Recursive ingest listing found 0 files / 2 folders
  in 3 read pages. No Graph writes were made by the operator.
- Stopped **only `PP-App-Serv/slots/staging`**, once. ARM and the stopped HTTP
  surface passed three subsequent read-only checks. The first immediate HTTP
  assertion failed during stop verification; no stop/restart command was repeated.
  SCM capture works while this slot is stopped. Its new protected snapshot
  exactly matches the pre-stop bytes/metadata, including its quota counter.
  Stopped-staging backup prefix: `304efbc9446e475ab93e291e8b51c21e`.
- Legacy main remains Running and serves v1.0.5 / `0ddfd05`. The shared plan
  and Pete were not stopped or modified. New apps remain read-only/ingestion-off.
- Both preparation leases were released and independently verified unlocked
  after reconciliation. No automatic lease break occurred. Recovery records
  remain in the owner-only directories recorded in the structured evidence.
- In IONOS, only record 1188155517 (`library` CNAME) TTL changed to 300.
  All four authoritative nameservers returned 300 with the unchanged
  `pp-app-serv.azurewebsites.net` destination by **19:55:10 UTC**. Conservatively
  wait until **20:55:10 UTC / 13:55:10 PDT** before relying on the shortened TTL.
  TXT, `www.library`, apex, Pete and other DNS records were not changed.

See `cutover-evidence/2026-10-23-containment-and-backups.json`.

Current local target-Linux suite: **459 passed**, network disabled, UID/GID 65532.
The common CI validation now also executes the release-channel restart/drain
smoke on the exact runtime image. Fresh CI scan/SBOM/deployment remains required.

### Remaining procedure (completed portions above are not replay instructions)

1. Record exact old main/staging commits, active/queued runs and current workflow
   state. With deployment-control authorization, disable exactly
   `azure-deploy.yml` in `Proxima-Partners/proxima-image-library` and verify it is
   disabled before any merge. Its current remote-main revision has no mode guard:
   setting `IMAGE_LIBRARY_RELEASE_MODE=hold` alone is not protection. Keep pilot
   mode `hold`. Do not cancel a running deployment midway; reconcile it first.
2. Retain the old route/certificate/app and export protected configuration and
   exact rollback source. Review and validate the branch's hold gate before any
   controlled re-enable. Do not merge then hope an old workflow skips deployment.
3. Establish a supervised quiet window with the sole user: finish/explicitly
   abandon uploads, previews, maintenance and SSE work. Inspect job completion
   evidence and ingest activity for **both** old slots. No process-level work
   counters exist in those deployed revisions. An empty ingest folder, low
   request count or 401 is not proof that workers are idle.
4. Select and approve one containment method before proceeding: a narrowly scoped
   legacy drain/worker-observability bridge tested against the exact legacy
   revisions, introduced only in that quiet window; or an explicitly supervised
   stop with documented unobservable-work limitations. This batch did not build
   or deploy a legacy bridge and does not silently substitute a stop for drain.
   Merely adding `INGEST_POLLER_ENABLED=false` to old code does not disable it.
5. Snapshot old main and staging separately after verified quiescence. Preserve
   both maintenance histories and the staging quota counter; review any merge
   explicitly. Do not copy all `/home`, discard history, promote saved approvals,
   replay staged uploads or assume a stopped app's SCM endpoint remains reachable.
   Confirm the chosen backup/restore transport before the interruption.
6. Keep old staging stopped/contained after handoff. Stop only exact Image Library
   apps/slots when approved, never the shared S1 plan or `PP-MCP-Server`.

## Supervised cutover gates still open

| Gate | Required evidence |
| --- | --- |
| Reviewed release | Commit and fresh CI test/scan/SBOM receipt for the exact published digest; local dirty-tree image is not a release |
| Safe old writers | Workflow hold and both-slot quiescence/containment verified |
| Recoverable state | Protected configuration/source/state backups, selected merge decision, UID 65532 transfer/restore proof |
| Runtime configuration | Preserve provider/MCP contracts; intentional fresh login; public URLs/callback/CORS/ingress reviewed |
| DNS/TLS | Target certificate/binding and direct TLS passed; renewal procedure, TTL reduction/wait and DNS transition remain; old route intact |
| New acceptance | Actual custom-domain TLS, fresh SSO/admin, v2.0.0, catalog/thumbnails/MCP and separated telemetry |
| Writable canary | User approved one clearly named disposable image, upload/thumbnail/metadata verification, then cleanup of only that asset; not yet run |
| Unattended release | Real adapter/lease/provenance/backup/cleanup and recovery rehearsal, not merely core unit tests |

The first window remains supervised. Reserve 60 minutes and begin rollback after
20 minutes without a healthy authenticated target. Before new writes, use the
retained route; after new writes, reconcile local state before any route rollback.
DNS recovery is not instant. Keep ingest off until one owner is approved; retain
legacy resources at least seven days. No backfill, data deletion or cleanup is
authorized by this preparation batch, apart from the explicitly approved single
disposable canary and cleanup of that exact asset after verification.

### TLS checkpoint

`/Users/mike-j4c/Downloads/liveproxima.org_ssl_certificate.cer` contains the
public wildcard certificate for `*.liveproxima.org` / `liveproxima.org`, valid
2026-10-20 through 2027-04-18. The user supplied the matching key at
`/Users/mike-j4c/Downloads/_.liveproxima.org_private_key.key`. RSA 2048 key match,
chain signatures, trusted-root/hostname/server-auth verification and encrypted
PFX roundtrip all passed. The original unencrypted key remains in Downloads;
its permissions were tightened from 0644 to owner-only 0600. The PFX and random
import password existed only in memory, never disk, command arguments, logs,
repository files or CI artifacts. Original certificate/key bytes were retained.

Imported certificate resource `image-library-tls-99c1349350b3`, thumbprint
`99C1349350B3A2F5E6DF36138DDC5F1E845A211F`, and prebound only
`pp-image-library/hostNameBindings/library.liveproxima.org` with SNI. Azure
imported certificates are webspace-scoped, not exclusively app-scoped. This was
imported using the dedicated plan in `PP-Resources-WestUS2webspace-Linux`;
the old app remains in `proxima-connector-rg-WestUS2webspace-Linux`.
The API's returned `serverFarmId` is null; successful target binding and exact
certificate delivery prove availability to the new app, not an app-only key ACL.

The first post-binding sequence encountered a certificate-verification error
after the version probe. No import/binding mutation was retried and no DNS change
was made; the infinite production lock was retained. Read-only reconciliation
confirmed both ARM objects and the intact old binding. Five subsequent complete
TLS/HTTP rounds to new IP `20.115.232.4`, using real SNI and strict chain/hostname
validation (no insecure bypass), passed: exact supplied certificate, v2.0.0,
commit `f7c58f0`, build `39914306153-1`, readiness 200, home 302 to `/login`, admin
401. Mount identity matches the default target hostname. The first error's
cause is not proven; retain it as a failed check, not a hidden success.

Both new slots remain read-only, ingestion off and operator-only ingress. The
initial full in-memory configuration comparison did not complete when that
verification process stopped; do not claim a full before/after settings proof.
No app-settings/ingress write calls occurred, and the explicit safety settings
were independently rechecked. The same owned lease was then released after
reconciliation; the lock blob is verified available/unlocked, not broken.

Public DNS still points to `pp-app-serv.azurewebsites.net`, serving v1.0.5;
TTL was not changed. The legacy IP `20.115.232.12` still serves its original
certificate, thumbprint `2183380CF203BAD19C1E81978AC71221F2D9831B`. No fresh
custom-domain SSO, protected transfer, canary or public cutover has occurred.
See `cutover-evidence/2026-10-23-tls-preparation.json` for the sanitized receipt.

Renewal is not yet automated: this is an uploaded certificate, not an Azure-
managed certificate. Target renewal by 2027-03-19 (30 days before expiry);
establish an expiry alert and either a reviewed IONOS replacement/import/binding
procedure or a separate approved switch to Azure-managed TLS after DNS cutover.
No alert, renewal job or Key Vault migration was created in this step. Follow
[Azure certificate requirements and webspace scope](https://learn.microsoft.com/en-us/azure/app-service/configure-ssl-certificate)
and [prebinding before DNS migration](https://learn.microsoft.com/en-us/azure/app-service/manage-custom-dns-migrate-domain).

## Maintenance procedure after acceptance

- Per release: immutable artifact, exact staged digest, bounded tests/scans,
  serialized promotion and durable evidence. Never rerun a deployed workflow.
- Daily, initially report-only: deployed-digest security scan, readiness and
  per-slot latency/error trends, expired/missing receipts and missed-run alert.
- Weekly: dependency/base-image update proposals, targeted compatibility tests,
  fresh image evidence. Separate major SDK/runtime changes; never extend security
  exceptions automatically or delete rollback images on a timer.
- Keep maintenance jobs out of the web request worker. Before scheduling the
  existing catalog-health script, add page/record/time limits, sampled thumbnails,
  explicit incomplete status and read-only credentials; it is not yet safe to
  schedule unchanged. Destructive jobs/backfills require their own reviewed scope.
- Do not use additional web workers/instances as an immediate speed fix: work
  admission, credential writes and local state still rely on a single process.
  Profile real per-slot requests after cutover before the next speed work batch.

## Validation evidence

See `cutover-evidence/2026-10-23-release-storage-and-controls.json` for this
follow-up's storage/lease checks, 418 target-Linux tests and offline smoke results.
The earlier `2026-10-23-preparation.json` and its image-security gate apply to
that earlier local image, not this changed source. A fresh exact-image scan/SBOM
and committed CI receipt remain required before publication. These do not prove live
Azure performance, provider authentication, TLS, telemetry ingestion or writes.
