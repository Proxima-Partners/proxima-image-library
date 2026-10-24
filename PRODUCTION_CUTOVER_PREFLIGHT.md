# Production cutover preflight

Date: 2026-10-23, America/Los_Angeles. Live read-only checks completed by 11:27 PDT (18:27 UTC).

Follow-up: the user subsequently approved local preparation-only implementation.
See `PRODUCTION_RELEASE_RUNBOOK.md` and the preparation evidence for those changes
and remaining gates. This preflight is the historical read-only snapshot, not a
claim that the subsequent code batch has been deployed or all blockers resolved.

## Decision

**NO-GO for public cutover until the preparation gates below pass.**
The isolated read-only container pilot remains healthy and passed; that is not a
writable-production acceptance result. This preflight changed no application code,
Azure configuration, DNS records, credentials, catalog data or deployment controls.
Only this report, its sanitized evidence and the status-document link were added
locally. No commit, push, deployment, restart, drain, state transfer or write canary
was performed.

Scope: Image Library only. Preserve `PP-MCP-Server`, the shared S1 plan, unrelated
DNS records and SharePoint assets. Existing downtime approval remains recorded;
the current request is preflight, not execution of the cutover.

## Verified now

| Gate | Evidence | Result |
| --- | --- | --- |
| Checkout and remote | Clean starting tree; `perf/container-pilot` and remote at `7158034`; remote `main` at `0ddfd05` | Pass |
| Public production | `library.liveproxima.org`: health/readiness/version 200, v1.0.5 / `0ddfd05`; anonymous homepage redirects to login | Healthy, unchanged |
| Pilot identity | Both new slots ready on build `39914306153-1`, commit `f7c58f0`, digest `3a7a7c24…`, v2.0.0; UID/GID 65532 | Pass |
| Pilot persistence | Independent Kudu sentinel hashes still match readiness and original main/staging identities | Pass |
| Compute and pulls | Dedicated `asp-image-library-p2v3`, P2v3 capacity 1; one main container/port 8080; managed-identity repository-reader roles scoped to `image-library` | Pass |
| Registry | Premium, ABAC repository permissions; admin and anonymous pull disabled | Pass |
| Isolation | Both new slots read-only, ingestion off, operator-only ingress; no temporary CI rules; `IMAGE_LIBRARY_PILOT_MODE=hold` | Pass |
| CI evidence | Latest evidence-only CI `39915917299` succeeded; retained passing release receipt matches running digest and expires 2026-11-21 23:59:59 UTC | Pass, not a fresh vulnerability rescan |
| Entra identity | Production callback already registered alongside both pilot callbacks; MSAL/SharePoint identity settings and admin allowlist match source in memory | No callback addition currently needed |
| IONOS access | User reauthenticated during preflight; exact `library` CNAME and `asuid.library` TXT visible in authenticated DNS UI | Pass |
| DNS | IONOS and authoritative nameserver agree: `library` → `pp-app-serv.azurewebsites.net`, TTL 3600 | Not switched |
| Existing TLS | Public certificate valid through 2027-03-17; SNI binding remains on old app | Old route recoverable while retained |

Fresh authenticated browser sign-in, admin access, thumbnails and MCP delivery on
the future custom-domain target remain execution gates. This turn checked live
anonymous auth boundaries, not a new end-to-end SSO session. The prior pilot's real
browser acceptance remains in `PILOT_ACCEPTANCE.md`.

## Blocking findings and preparation work

### 1. Legacy writers cannot use the pilot's drain API

Old production runs `0ddfd05`; old staging runs `cdd3ebf`. Both are running, have
`STORAGE_MODE=sharepoint` and the same `Images/Ingrest-images` folder configured.
Both exact revisions start the poller whenever those settings are present; they
do not implement the new deployment drain/active-work controls. Adding
`INGEST_POLLER_ENABLED=false` to those old revisions alone will NOT disable them.

The recursive ingest-folder read completed in three pages: two subfolders,
zero files. The shared ingest log showed recent empty scans and was modified at
18:19 UTC. Empty scans still write that log. This proves ongoing background
activity, not which slot wrote it or that all worker activity is idle. No duplicate
asset processing was established.

Required: a reviewed legacy quiescence procedure before any restart/stop or state
snapshot. Prefer a narrowly scoped, tested containment bridge with persistent
drain and observable active work, including background threads/SSE. Introducing
that bridge itself needs a confirmed quiet window; do not deploy it over unknown
active work. If an alternative supervised stop procedure is selected, explicitly
establish no active uploads, maintenance, previews or ingest and document its
limitations. Do not treat low traffic, an empty directory or a 401 response as
proof of idle. Keep old staging disabled after the handoff; never stop the plan.

### 2. State is small, but old main and staging have different histories

Authenticated Kudu VFS reads, without writes:

| Required state | Old main | Old staging | New main |
| --- | --- | --- | --- |
| Staged uploads | Empty | Empty | Absent |
| Maintenance state | 806 bytes; 1 audit entry | 7,648 bytes; 21 audit entries | Absent |
| Maintenance checkpoint directory | Absent | Absent | Absent |
| Stock quota counter | Absent | June 2026, count 3; 32 bytes | Absent |
| Persistent stock-key file | Absent at planned path | Absent at planned path | Absent |
| Tag fallback | Absent at checked `/home` paths | Absent at checked `/home` paths | Absent |

Scheduled maintenance is disabled in both old files; no recorded checkpoints or
approvals. File absence is a scoped path observation, not a claim that the entire
filesystem contains no other state. SharePoint `Config/tag_library.json` exists
(5,836 bytes) and remains authoritative. No tag file was seeded or changed.

Required: take protected, separately identified backups of BOTH old slots after
quiescence; preserve their names/sizes/hashes and permissions. Use current main
as the default live-state source, but review old staging's additional audit history
and historical counter before deciding any merge. Do not silently reset quotas,
discard history, promote approvals or replay consumed uploads. No backup of file
contents or protected configuration was created by this preflight. Reinventory
immediately before transfer; verify target UID 65532 can read/write/rename the
selected transferred state. Do not copy Oryx output, old virtualenvs or all `/home`.

### 3. Pilot configuration is intentionally not production-complete

- New main lacks the source's Anthropic, Pexels, Shutterstock, Unsplash and Pixabay
  credentials. Preserve existing provider accounts; transfer only reviewed runtime
  keys over the authenticated control plane, without logging values/hashes.
- New `MCP_INTERNAL_SECRET` differs from production. Preserve the current production
  MCP contract at cutover rather than silently breaking existing callers or rotating
  their credentials. Inventory callers/old direct-host URLs before changing routing.
- New Flask session key differs intentionally. Prefer retaining the new key and
  requiring a fresh sign-in, rather than promising seamless session continuity.
- Set new main `APP_BASE_URL` and `MSAL_REDIRECT_URI` to the real public domain at
  the controlled transition. Review CORS: old production includes Webflow origins;
  the pilot allows only its own hostname. Do not silently remove existing consumers.
- The six explicit source upload/rate limits match the new code defaults: 20 MiB
  ordinary upload, 500 MiB admin upload, 160 MiB request limit, and 20 auth / 8
  stream requests per 60 seconds. Preserve that effective contract. Do not
  bulk-copy obsolete Azure/Oryx/auth-provider credentials or settings.
- New main currently allows only the operator IP. Establish the intended user/MCP
  access policy while retaining authentication and independently restricted SCM.
  Do not make staging public or broadly disable network controls as a shortcut.
- Before enabling writes, set `PILOT_STATE_PROBE_ENABLED=false`; its startup check
  deliberately rejects writable mode. Keep ingestion disabled until a single owner
  is explicitly selected; the owner check uses `WEBSITE_HOSTNAME`, not the CNAME.

**Concrete persistence issue:** the pilot has `PYTHON_DOTENV_DISABLED=1` while
`src/config.py:13` uses `load_dotenv` for `/home/proxima_stock_keys.env`. The pinned
python-dotenv 1.2.4 implementation skips that load. UI-saved provider changes
therefore cannot be assumed to survive restart; Azure environment values also
take precedence over the file. Add an explicit, allowlisted persistent-key loading
policy and restart/precedence tests, or intentionally make the UI read-only for
environment-managed keys. Do not simply enable loading arbitrary bundled `.env`
files. Verified against the [pinned package](https://pypi.org/project/python-dotenv/1.2.4/)
and its wheel digest without installation. The local `.venv` has older dotenv
1.0.0 and is not the authoritative container validation environment.

### 4. Domain ownership is ready; target TLS and DNS timing are not

The old and new apps have different ARM webspaces. The existing `asuid.library`
TXT matches BOTH apps' verification ID, so no replacement of that TXT is currently
needed. The new app has no `library.liveproxima.org` hostname or certificate binding.
The existing certificate is an App Service managed certificate in the legacy
webspace; do not assume its thumbprint can be reused on the new app or export it.

Preparation sequence:

1. After authorization, lower ONLY the `library` CNAME TTL from 3600 to 300 if
   supported. Preserve its old value and wait at least the prior 3600 seconds.
2. Validate/prebind the public hostname to the new app while leaving the old
   binding intact. Different webspaces support that approach, but actual binding
   success remains untested until the approved mutation.
3. Prefer a DNS-validated certificate provisioned and bound to the new app BEFORE
   routing traffic. This permits forced-resolution TLS/custom-domain checks while
   DNS still points to old production. Confirm certificate source, renewal owner
   and any purchase/permissions separately; none was acquired here.
4. Alternative: explicitly accept certificate-issuance downtime and request a new
   ASMC after the CNAME points to the new app. Keep a bounded issuance deadline and
   the intact old binding/certificate for rollback. Do not promise issuance within
   the outage target.

Microsoft documents [domain prebinding and post-routing ASMC issuance](https://learn.microsoft.com/en-us/azure/app-service/manage-custom-dns-migrate-domain)
and [certificate webspace scope/non-exportability](https://learn.microsoft.com/en-us/azure/app-service/configure-ssl-certificate).
The [November 2025 ASMC update](https://learn.microsoft.com/en-us/azure/app-service/app-service-managed-certificate-changes-july-2025)
allows CA validation at the Azure frontend despite app access restrictions; do not
open the app to the world merely for certificate issuance. Correct public DNS is
still required. Leave apex/www, mail, Pete and `www.library` records untouched.

### 5. Telemetry must distinguish production from staging

`src/telemetry.py:95` hardcodes the same role/build identity for both slots. Setting
`OTEL_SERVICE_NAME` alone will not override this explicit resource construction.
Implement and test a small allowlisted slot/environment label, preserving the
privacy filter. Rebuild/test/scan the changed image, deploy read-only, and verify
actual per-slot request/dependency ingestion. Do not report per-slot error rates
from the current combined role/build telemetry.

A fresh 30-minute Insights query returned 21 requests under the same combined
role/build: six 200s, thirteen 302s and two 401s. The 401s are consistent with this
preflight's intentional anonymous admin-status checks; this is not a claim of
zero failures or proof of fresh authenticated acceptance.

### 6. A pilot hold is not a production release lock or writable release controller

Remote `main` still contains the older `azure-deploy.yml` with automatic source
deployment/swap on push and no release-mode condition. The workflow is active.
The safer `IMAGE_LIBRARY_RELEASE_MODE` guard exists only on the pilot branch;
setting that variable alone would NOT lock the current main workflow. No runs
were in progress among the ten latest inspected runs; this is not a durable lock.

Before merge/cutover, explicitly disable the exact legacy deployment workflow or
land a reviewed hold gate under controlled conditions; verify no queued/active
deployments. Do not merge the pilot branch and let the old source path run.

The current in-place helper also deliberately requires `APP_READ_ONLY=true` and
`PILOT_STATE_PROBE_ENABLED=true`. It cannot operate writable production unchanged.
Implement a separate production policy with exact target/receipt guards, drain,
state preservation, one reconciled rollback, cleanup and serialized promotion.
Keep pilot fail-closed checks intact; do not relax them to accommodate production.
Prepare this controller before enabling unattended production releases.

The legacy release run retains validation reports, not a release ZIP. Archive the
exact rollback source/configuration/state before the window and keep the old app
intact. Healthy retained apps are useful rollback targets, not substitutes for a
verified restore procedure.

## Recommended execution order — not executed by this report

1. **Preparation-only implementation:** production telemetry label; persistent-key
   behavior; production deployment controller and legacy containment/lock plan;
   focused tests plus fresh full target-image CI/security evidence. Work on a
   reviewed branch, not a deployment-triggering `main` push. No DNS cutover.
2. **Approved non-traffic preparation:** protected rollback exports; explicit
   configuration/state transfer manifests; intended ingress/MCP contract; lower
   TTL and wait; prebind hostname and prepare the chosen certificate. Keep new
   main read-only and all new automatic ingest disabled.
3. **Go/no-go:** all blocking gates above closed, exact image/receipts verified,
   old/new state manifest frozen, no active work, certificate/domain recovery
   ready, and first supervised window confirmed. Request one named disposable
   test asset and its write-canary scope before any canary; none is designated yet.
4. **Window:** quiesce old main AND old staging; snapshot/transfer selected state;
   ensure a single writer; configure the public hostname/callback; change only the
   approved CNAME. Verify TLS, real SSO/admin protection, v2.0.0, catalog/thumbnails,
   MCP reads and per-slot telemetry at `library.liveproxima.org` before writes.
5. **Writable acceptance:** disable pilot-only startup probe, enable normal writes
   under the production policy, run only the approved small canary, verify results.
   Ingest remains off unless separately resumed with one owner. Observe 24 hours;
   retain old resources/artifacts at least seven days. No cleanup/backfills implied.

Reserve 60 minutes; 15–30 minutes interruption is only a planning target. Begin
rollback after 20 minutes without a healthy authenticated target. Before any new
writes, route rollback can restore the preserved old hostname/CNAME/TLS path. After
new writes, first reconcile changed local state; never overwrite it with the old
snapshot or reverse SharePoint changes automatically. DNS rollback is not instant.

## Method and limitations

Read-only Azure CLI/ARM, scoped Resource Graph, GitHub status/refs, authoritative
DNS, public HTTPS/TLS, authenticated Kudu VFS and bounded Microsoft Graph reads.
Secret comparisons stayed in memory and only presence/equality results were
reported. No application import, provider purchase, AI generation, catalog write,
load test or mutating health-check script was run.

The Azure resource-lookup skill kept inventory scoped to the subscription/resource
group. The generic azure-validate workflow requires an azd preparation plan, while
this existing project is GitHub Actions/Azure CLI based and azure-prepare explicitly
excludes non-azd projects. The repo-specific preflight was used instead; no formal
`Validated` status or azd artifacts were invented. Fresh tests/scans are required
for the proposed fixes; the prior 255-test pilot result was not rerun or relabeled.

See `cutover-evidence/2026-10-23-preflight.json` for sanitized state fingerprints and
`PILOT_ACCEPTANCE.md` for completed pilot measurements/recovery evidence.
