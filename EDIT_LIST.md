# Edit List

Pending changes — rebuild only on approval.

---

## Pending

- T1. Comprehensive pre-production testing protocol — in progress (local validation complete; Azure configuration and live production validation pending)
- T2. Security protocol audit & penetration checklist — local hardening complete; production verification pending Azure rollout
- T3. Comprehensive pre-production code audit — not started

---

## Future Development Queue

### T1. Comprehensive pre-production testing protocol

Develop and execute a full test protocol before any Azure production deployment.

**Authentication & session:**

- MSAL login flow (valid user, invalid user, expired token)
- Session persistence across server restart
- Logout clears session correctly
- Unauthenticated API calls return 401, not redirect loops

**Image processing pipeline:**

- Upload JPEG, PNG, WebP, GIF — verify WebP conversion, 1600px cap, metadata generation
- Upload CMYK JPEG (known edge case) — verify color space conversion
- Upload oversized file — verify resize behavior
- Upload duplicate filename — verify slug uniqueness
- Verify alt text ≤ 125 chars, no "Image of" prefix
- Verify tags are from approved vocabulary only

**Library search & browse:**

- Keyword search returns relevant results
- Category filter narrows correctly
- Tag filter works in combination with keyword
- Pagination / load-more under large result sets
- Thumbnails load for all records (no broken images)

**Review workflow:**

- Pending badge count matches actual pending-review records
- Approve / Reject / Archive each update status correctly
- Approve All fires all updates and badge drops to zero
- Badge refreshes on return to home page (pageshow + interval)
- Concurrent approvals do not corrupt local_table.json (threading lock)

**Stock photo search:**

- Pexels, Shutterstock, Unsplash, Pixabay each return results
- Shutterstock quota gate triggers at limit
- "Add to Library" SSE stream completes and record appears in library
- Downloaded image lands in correct High-Res source folder

**MCP tools (Claude Desktop):**

- `search_image_library` returns results for a known keyword
- `catalog_image_from_file` processes a base64 image and creates a pending-review record
- MCP server survives Claude Desktop restart without path errors

**Tag manager:**

- Add, remove, promote tags
- Promoted tags appear in search filter
- Changes persist across server restart

**Maintenance utilities (post-M1–M20):**

- Each utility completes without error in TEST_MODE
- Orphan finder correctly identifies staged test orphans
- CSV export produces valid file with all fields
- M10-M19 endpoints pass smoke checks (health, integrity, drift, normalization, checkpointing, jobs, audit, guardrails, approvals)
- Two-step approval gate blocks destructive actions without approved token when enabled

**Performance:**

- Library with 250+ records loads hero and recent strip in < 2 s
- Stock search (all 4 APIs, 12 results each) completes within 25 s timeout
- SSE streams (catalog, scan) do not hang or timeout prematurely

**Production environment checklist:**

- All env vars set (see development.md — 40+ vars)
- `FLASK_SECRET_KEY` is a random secret (not dev default)
- `TEST_MODE=false`, `STORAGE_MODE=sharepoint`
- SharePoint List fields match schema in specification.md
- Azure App Service health check passes (`/health` returns 200)
- MSAL redirect URI matches Azure AD app registration

### T2. Security protocol audit & penetration test checklist

Review and validate security best practices before production deployment.

**Authentication & authorization:**

- All routes (except `/health`, `/login`, `/auth/callback`) require valid MSAL session
- API endpoints return 401 JSON (not redirect) for unauthenticated requests
- Session cookie has `HttpOnly` and `Secure` flags set in production
- `FLASK_SECRET_KEY` is a cryptographically random value (≥ 32 bytes), never the dev default
- Token expiry is enforced — expired MSAL tokens trigger re-login, not silent bypass
- Verify no routes expose user data without `@login_required`

**Input validation & injection:**

- File upload: verify only allowed MIME types accepted (JPEG, PNG, WebP, GIF); reject `.exe`, `.php`, `.js`, etc.
- File upload: verify filename is sanitized before use — no path traversal (`../../../etc/passwd`)
- All API parameters validated before use; unexpected fields silently ignored
- Search query strings are parameterized — no SQL/NoSQL injection surface
- Alt text and tag fields: verify no XSS payloads are stored or reflected unescaped in UI
- SSE endpoint parameters validated; no arbitrary command execution via `_stream_command`

**Path traversal & file access:**

- `/thumbnail` and `/image` endpoints verify path is within `IMAGE_FOLDER` before serving
- Requests for `../../etc/passwd` or similar return 400/404, not file contents
- `catalog_image_from_file` MCP tool validates `category` is an approved value, not a path component

**Secrets & environment:**

- `.env` is in `.gitignore` and never committed
- No API keys, secrets, or credentials hardcoded in source files
- `ANTHROPIC_API_KEY`, `MSAL_CLIENT_SECRET`, stock API keys confirmed absent from git history
- Azure App Service environment variables set via portal, not checked-in config files

**Transport security:**

- Production runs HTTPS only; HTTP redirects to HTTPS
- CORS policy (`ALLOWED_ORIGINS`) is restricted to known domains — not wildcard `*`
- `Referrer-Policy`, `X-Content-Type-Options`, `X-Frame-Options` headers present in responses

**Dependency audit:**

- Run `pip audit` (or `safety check`) against `requirements.txt`
- No known CVEs in Pillow, Flask, MSAL, or other direct dependencies
- Pin all dependency versions in `requirements.txt` to prevent supply chain drift

**Rate limiting & abuse:**

- Stock API endpoints are not publicly callable without auth
- `/api/upload/stage` and `/api/catalog-stock` cannot be called in a loop by an unauthenticated actor
- Shutterstock quota gate prevents runaway spend
- No sensitive error details (stack traces, file paths) exposed in production API responses

**Logging & monitoring:**

- Failed login attempts are logged
- 4xx/5xx errors are captured and visible in Azure App Service logs
- No passwords, tokens, or PII written to logs

### T3. Comprehensive pre-production code audit

Systematic review of the entire codebase before Azure production deployment. Goal: no dead code, no redundancy, no latency surprises, consistent conventions throughout.

**Unused code & dead paths:**

- Confirm no legacy Airtable references remain in source/docs (spot-check after merges)
- Audit all `@app.route` endpoints — identify any that are unreachable or no longer wired to a UI
- Remove commented-out code blocks throughout `src/app.py`, `src/image_processor.py`, `src/mcp_server.py`
- Check `src/__init__.py` for stale imports
- Identify any template files with no corresponding route
- Check `static/` for unused CSS, JS, or image assets

**Redundancy:**

- Review `LocalClient` and `SharePointListClient` for duplicate logic that should be in a shared base class or helper
- Audit `src/app.py` for repeated patterns (e.g. `get_client()` calls, error response formatting) that should be factored into helpers
- Check for duplicate route logic between `/run/scan-test` and `/run/scan-live`
- Review stock client classes for shared fetch/retry logic that could be consolidated

**Latency & performance:**

- Profile `/api/images` under 250+ records — ensure filter and sort happen server-side, not in JS
- Verify `_records_cache` is invalidated correctly on all write paths (upload, status patch, scan)
- Audit SharePoint Graph API calls — identify N+1 patterns (e.g. fetching CDN URLs one-by-one vs. batch)
- Review SSE endpoints for blocking operations that should be offloaded to threads
- Check thumbnail generation — ensure it is not re-running Pillow on every request for the same image (consider disk cache)
- Audit `_sp_url_cache` TTL — confirm 45-min TTL is appropriate for production CDN URL lifetime

**Error handling:**

- All `except Exception` blocks should log the error with context, not silently pass or return vague messages
- Review every `try/except` in `src/app.py` — verify HTTP status codes are correct (400 for bad input, 404 for not found, 500 for server fault)
- MCP server: verify all tool errors return structured error responses, not unhandled exceptions
- SSE streams: confirm `finally` blocks close queues and threads on client disconnect

**Code consistency & conventions:**

- Confirm all Claude calls use `claude-sonnet-4-6` (no stray model strings)
- Verify all status values use hyphens (`pending-review`, not `pending_review`)
- File naming: confirm all new records follow `{prefix}-{slug}.{ext}` convention from specification.md
- Confirm `ensure_ascii=False` on all `json.dump` calls
- Review all f-strings and format calls for potential injection or encoding issues
- Check all `Path` usage — no raw string concatenation for file paths

**Configuration & environment:**

- Audit `src/config.py` — remove any env vars that are no longer used
- Verify all config values have sensible defaults and fail loudly (not silently) when required vars are missing
- Confirm `TEST_MODE` and `STORAGE_MODE` gate every code path that touches files or the list client

**Documentation alignment:**

- Verify `development.md` matches current architecture (no Airtable refs, correct env var list, accurate setup steps)
- Verify `specification.md` field schema matches actual SharePoint List columns and `LocalClient` JSON structure
- Confirm `README.md` quick-start instructions are accurate and produce a working local environment

**Tooling:**

- Run `flake8` or `ruff` across `src/` — resolve all warnings
- Run `mypy` (or pyright) in strict mode — resolve type errors in public interfaces
- Run `pip audit` — resolve any CVEs (overlaps with T2)
- Confirm all tests in `tests/` pass cleanly against the current codebase

## Applied

### T1.A — Baseline pre-production smoke checks — applied 2026-04-05

- Ran `.venv/bin/python3 -m pytest -v`: 19/19 tests passed
- Ran `Sync Images (TEST_MODE)`: processed 1 new image and completed status report without runtime error
- Auth gate validation with `DEV_AUTH_BYPASS=false`:
  - `GET /api/images` -> 401 JSON (`{"error":"Authentication required"}`)
  - `GET /api/pending-count` -> 401 JSON (`{"error":"Authentication required"}`)
  - `GET /api/maintenance/orphans` -> 401 JSON (`{"error":"Authentication required"}`)
  - `GET /` -> 302 to `/login`, and `/login` -> 302 to Microsoft authorize URL
- TEST_MODE endpoint smoke checks passed for: `/health`, `/api/pending-count`, `/api/images`
- Maintenance endpoint smoke checks passed for:
  - `/api/maintenance/duplicates`, `/api/maintenance/orphans`, `/api/maintenance/export-csv`
  - `/api/maintenance/health-snapshot`, `/api/maintenance/integrity-scorecard`, `/api/maintenance/aging-drift`, `/api/maintenance/quality-drift-queue`, `/api/maintenance/category-normalization/preview`, `/api/maintenance/checkpoints`, `/api/maintenance/scheduled-jobs`, `/api/maintenance/audit`, `/api/maintenance/guardrails`, `/api/maintenance/approvals`

### T1.B — Image/review/tag/stock/MCP functional checks — applied 2026-04-05

- Upload stage acceptance validated for JPEG, PNG, WebP, GIF via `/api/upload/stage`
- CMYK JPEG processed successfully through `/api/upload/process` (metadata generated, pending-review record created)
- Oversized JPEG processed successfully and resized WebP verified at `1600x1100` (max side cap enforced)
- Duplicate filename flow verified: two ingests of same source produced unique slugs/filenames
- Alt text checks passed for sampled processed records:
  - length <= 125 chars
  - no `Image of` / `Picture of` prefix
- Tag checks passed for sampled processed records: non-suggested tags stayed inside approved vocabulary; suggestions were `?`-prefixed
- Review workflow checks passed:
  - `/api/pending-count` matched `/api/images?status=pending-review`
  - `/api/image-status` transitions verified for approved/rejected/archived/pending-review
  - Concurrent status updates succeeded (HTTP 200) and `test_data/local_table.json` remained valid JSON
- Tag manager checks passed:
  - add, promote suggestion, remove via `/api/tag-library/*`
  - promoted tag persisted in library responses before removal
- Stock flow checks passed:
  - `/api/stock-search` returned results from Pexels/Unsplash/Pixabay in ~1.5s (under 25s target)
  - `/api/catalog-stock` SSE completed in ~4.5s with result payload
  - cataloged stock image landed in `High-Res/Pexels/...` and pending-review metadata created
  - Shutterstock quota counters (`/api/shutterstock/quota`, `/api/shutterstock/track`) incremented correctly
- MCP checks passed:
  - `search_image_library` returned text + thumbnail results for known phrase
  - `catalog_image_from_file` accepted base64 image and created pending-review record

### T2.A — App-layer security hardening — applied 2026-04-09

- Restricted `/run/*` routes to maintenance admins via the existing maintenance allowlist
- Enforced production-safe config validation:
  - non-test runtime rejects default or weak `FLASK_SECRET_KEY`
  - non-test runtime rejects invalid upload and rate-limit settings
- Hardened Flask session config for production with `HttpOnly`, configurable `Secure`, and `SameSite`
- Added CSRF token generation and validation for SSE/browser-triggered flows
- Enforced same-origin checks on mutating browser requests
- Added response security headers:
  - `Content-Security-Policy`
  - `Strict-Transport-Security` when served via HTTPS
  - `X-Content-Type-Options`
  - `X-Frame-Options`
  - `Referrer-Policy`
  - `Permissions-Policy`
  - `Cross-Origin-Opener-Policy`
- Added lightweight in-process rate limiting for auth-sensitive and streaming endpoints
- Added upload and remote-download image validation:
  - max file size enforcement
  - content verification via Pillow instead of extension-only trust
  - bounded remote downloads before ingest
- Updated browser templates and the T1 harness to satisfy CSRF and same-origin protections
- Added regression coverage in `tests/test_security_controls.py`

### T2.B — Dependency audit and pinning — applied 2026-04-09

- Ran `pip-audit` against `requirements.txt`
- Upgraded `requests` from `2.31.0` to `2.33.0` to clear known CVEs
- Pinned direct dependencies to exact versions to reduce supply-chain drift
- Re-ran dependency audit successfully with no known vulnerabilities reported
- Re-ran `pytest -v` and the T1 regression suite successfully after dependency changes

### T1.C — Performance and destructive guardrail verification — applied 2026-04-05

- `/api/images` performance check at 260 records:
  - 5-run max response time: ~0.0066s
  - Average response time: ~0.0029s
  - Meets T1 target `< 2s` under local TEST_MODE conditions
- Two-step destructive approval guardrail verified end-to-end:
  - Enabled `two_step_approval_required=true`
  - Destructive call without `approval_token` returned 403 (`approval_token is required by guardrails`)
  - Approval token requested + approved via `/api/maintenance/approvals/*`
  - Same destructive call succeeded with approved token and deleted target record
  - Guardrail configuration restored to prior state after test

### T1.D — Auth/session non-interactive validation — applied 2026-04-05

- Ran isolated auth-required server on port `5002` with `TEST_MODE=true`, `DEV_AUTH_BYPASS=false`
- Verified unauthenticated API behavior:
  - `GET /api/images` -> 401 JSON (`{"error":"Authentication required"}`)
- Verified login redirect behavior:
  - `GET /login` -> 302 redirect to Microsoft authorize URL
- Verified callback error path (simulated denied auth):
  - `GET /auth/callback?error=access_denied...` -> 401 login error page
- Verified authenticated-session gate behavior using signed Flask session cookie:
  - Protected API returns 200 while authenticated cookie is present
- Verified logout clears session:
  - `GET /logout` -> redirect
  - subsequent protected API request with same client -> 401
- Verified session persistence across server restart:
  - authenticated signed session cookie accepted before restart
  - same cookie accepted after restart (protected API remained 200)
- Remaining manual auth checks for T1:
  - real valid-user MSAL sign-in flow in browser
  - real invalid-user MSAL sign-in outcome from identity provider
  - expired-token behavior after real token issuance/expiry window

### T1.E — Library/review UI behavior validation — applied 2026-04-05 (partial)

- Search relevance checks passed (client-side token match behavior):
  - `san francisco` -> 70 matches
  - `logo` -> 28 matches
  - `golden gate` -> 15 matches
- Tag + keyword combo check passed (example: `icon` + `diagram` produced expected result set)
- Thumbnail integrity check passed:
  - 259 thumbnails requested via `/thumbnail?path=...`
  - 0 broken responses
- Review queue approve-all behavior validated via API-equivalent flow:
  - pending before run: 6
  - after batch approve: 0 pending
  - records restored back to pending-review after test
- Badge refresh hooks confirmed in UI code:
  - interval refresh present (`setInterval(refreshReviewBadge, 30000)`)
  - return-to-page refresh present (`pageshow` listener)
- Approve-all wiring confirmed in UI code:
  - `Approve all` button exists in `review.html`
  - batch action uses `Promise.all(...)`

**Gaps found during T1.E:**

- Category filter mismatch for nested folders (functional bug):
  - UI `renderGrid()` compares only first location segment (`img.location.split('/')[0]`)
  - Sidebar folder selection uses full folder values (for example `photography/SanFrancisco_Images`)
  - Result: 7/7 nested-folder categories returned incorrect (zero) results in test
- No pagination/load-more behavior implemented in library UI:
  - no `load more` control
  - no pagination logic in `index.html`
  - grid renders entire filtered set at once

### T1.E.1 — UI gap remediation and revalidation — applied 2026-04-05

- Implemented nested-folder category filter fix in `templates/index.html`:
  - `renderGrid()` now compares selected folder against the image parent folder path
  - corrected mismatch for nested category values (for example `photography/SanFrancisco_Images`)
- Implemented load-more pagination in `templates/index.html`:
  - added `PAGE_SIZE` paging state and filter-key reset behavior
  - added `Load more` control and `Showing X of Y` status in browse view
  - grid now renders incrementally rather than all filtered records at once
- Re-ran T1.E validation after fix:
  - nested-folder mismatch count: `0` (was `7`)
  - pagination/load-more controls: present and wired
  - thumbnail integrity recheck: `259` checked, `0` broken
  - approve-all equivalent behavior recheck: pending dropped to `0` and restored successfully
- T1.E previously identified gaps are now resolved.

### T1.F — Production readiness preflight — applied 2026-04-05 (partial)

- Environment/config preflight completed (non-sensitive checks):
  - required production key set present count: 19/19 in `.env`
  - `FLASK_SECRET_KEY` strength check passed (length 64, non-default)
  - `.gitignore` includes `.env`
- Current mode flags indicate **local/dev** runtime (not production):
  - `TEST_MODE=true`
  - `STORAGE_MODE=local`
  - `DEV_AUTH_BYPASS=true`
- Health endpoint checks passed in running app:
  - `GET /health` -> 200
  - `GET /healthz` -> 200
- Schema alignment checks passed at code/spec level:
  - `specification.md` record fields align with local metadata client field keys
  - SharePoint list client mapping aligns with spec (`Title/AltText/Tags/Status/Slug/Location/HighResLocation/Source`)
- Deployment checklist cross-check (`PRODUCTION_DEPLOY.md`) confirms required production switches and redirect-URI setup steps are documented.

**Remaining for full T1.F completion (environment-dependent):**

- Flip runtime to production values and re-validate:
  - `TEST_MODE=false`
  - `STORAGE_MODE=sharepoint`
  - `DEV_AUTH_BYPASS=false`
- Verify Azure App Service live health endpoints in deployed environment
- Verify Azure AD app registration contains the production `MSAL_REDIRECT_URI`
- Verify SharePoint List columns exist in the live tenant and match expected internal names

### T1.G — Automated T1 regression harness — applied 2026-04-05

- Added isolated, repeatable T1 automation runner: `scripts/run_t1_suite.py`
  - seeds deterministic local fixture data and images
  - starts/stops Flask test servers automatically (bypass and auth-required modes)
  - validates health, smoke endpoints, review transitions, pending-count consistency, thumbnail integrity, nested-folder behavior, and UI wiring (badge refresh, approve-all, load-more)
  - validates non-interactive auth gate behavior (`401` APIs + `/` redirect to `/login`) without requiring external MSAL tenant discovery
  - writes JSON report (`test_data/t1_last_report.json`) and exits non-zero on regression failures
- Added pytest wrapper test: `tests/test_t1_suite.py` to run the T1 automation suite in test runs
- Added VS Code task: `Run T1 Regression Suite`
- Added CI workflow: `.github/workflows/t1-regression.yml`
  - runs on `push` and `pull_request` to `main`
  - executes T1 suite and uploads JSON report artifact
- Added README command entry for running the automated T1 suite

### T1.H — Manual auth validation completion (local scope) — applied 2026-04-05

- Valid-user MSAL browser login check passed in local auth-required mode
- Invalid-user MSAL browser login check passed (tenant denial for non-member account)
- Session-expiry behavior validated in local TEST_MODE:
  - enforced `exp` claim validation for authenticated sessions
  - added `POST /auth/test-expire-session` (TEST_MODE only) to force expiry for deterministic testing
  - forced interactive sign-in prompt after forced expiry to avoid silent SSO masking
- Forced-expiry verification passed:
  - protected API requests return 401 after expiry
  - page routes redirect to `/login` until re-authenticated
- Remaining blocker for full T1 closure:
  - production checks in T1.F cannot complete until Azure App Service deployment is available

### W1. Proxima Writing → Image Library → Webflow CMS integration — applied 2026-04-05

- Confirmed Blog Writing Skill, Article Writing Skill, and Branding Skill are complete and correctly wired
- Confirmed all 4 Image Library MCP tools (`search_image_library`, `search_stock_photos`, `catalog_stock_image`, `catalog_image_from_file`) are implemented and registered in Claude Desktop
- Confirmed all stock photo API keys present in `.env` (Pexels, Unsplash, Pixabay, Shutterstock)
- Added **Webflow CMS Publishing** section to `Project-Instructions.md`:
  - Mapped Blog output (13 fields) to Blog Items collection field slugs
  - Mapped Article output (10 fields) to Article Items collection field slugs
  - Hardcoded stable reference IDs: Authors, Blog categories, Article types (all from proxima.cafe)
  - Dynamic tag ID lookup via `list_collection_items` on Tags collection
  - Image field handling: SharePoint CDN URL in production; local mode requires manual upload
  - Draft creation via `create_collection_items`; optional live publish via `publish_collection_items`
  - Noted gap: Blog category "Story" not yet in Webflow Categories — instructions offer to create it
- Added **URL Slug** field to Article Skill output format (required by Webflow Article Items collection)
- Image field in local/test mode cannot be auto-set (localhost URL not publicly accessible); user notified to set manually in Webflow Designer

### 20. M10-M19 — Maintenance governance and quality operations — applied 2026-04-05

- Added M10 health snapshot endpoint and UI action for one-click operational overview
- Added M11 integrity scorecard endpoint and per-category completeness metrics
- Added M12 aging/drift scan endpoint with staleness and metadata-quality signals
- Added M13 quality drift queue and mark endpoint for retag candidate workflow
- Added M14 category normalization preview/apply endpoints with optional pending-review reset
- Added M15 checkpoint create/list/restore support with persisted checkpoint metadata
- Added M16 scheduled maintenance jobs list/config/run support with run summaries
- Added M17 audit-trail listing and durable audit append integration across maintenance actions
- Added M18 guardrail get/update support (batch cap, preview requirement, optional checkpointing, optional two-step approval)
- Added M19 approval request/approve/list flows and destructive endpoint enforcement via approval token consumption
- Validated with endpoint smoke checks and guarded destructive-flow test (blocked without token, succeeds with approved token)

### 19. M20 — Maintenance efficiency and redundancy refactor — applied 2026-04-05

- Added shared maintenance backend helpers for record snapshot access, record-id parsing, bulk deletes, and bulk field patching
- Refactored maintenance endpoints to use one record snapshot per operation and centralized bulk update/delete paths
- Added `bulk_patch_fields` and `bulk_delete_records` in local and SharePoint clients (single-write local; bounded parallel SharePoint)
- Optimized near-alt duplicate detection using bounded lexical-window comparisons to reduce worst-case scan time on larger datasets
- Deduplicated maintenance page JavaScript with reusable scan handlers and shared `PURGE` confirmation helper
- Validated with tests and timed benchmark at 600 records

### 18. M6 — Maintenance page export to CSV — applied 2026-04-05

- Added `GET /api/maintenance/export-csv` to export library metadata as CSV
- Export columns: `id`, `filename`, `category`, `alt_text`, `tags`, `status`, `location`
- Added optional export filters by category and status via query params
- Added Export CSV section in Maintenance UI with filter controls and one-click download

### 17. M5 — Maintenance page status reset — applied 2026-04-05

- Added `GET /api/maintenance/status-reset-preview` for filter preview with category/tag/status/date-range and max-record limits
- Added `POST /api/maintenance/status-reset` with `confirm_token=PURGE` and stale preview count protection
- Status reset updates matching records to `pending-review` while reporting updated/unchanged/failed counts
- Date-range filtering supports ISO date inputs and reports records skipped due to missing date fields
- Added Status Reset section in Maintenance UI with preview summary, confirmation prompt, and execution results

### 16. M4 — Maintenance page broken thumbnail checker — applied 2026-04-05

- Added `GET /api/maintenance/broken-thumbnails` to validate thumbnail locations across all records
- Checker flags missing location, missing file, unreadable/corrupt image, and load errors in both local and SharePoint modes
- Added `POST /api/maintenance/broken-thumbnails/delete-records` with `confirm_token=PURGE` for bulk cleanup
- Added `POST /api/maintenance/broken-thumbnails/relink` to set a new `Location` with optional existence verification and status reset
- Added Broken Thumbnail Checker section in Maintenance UI with scan results, relink workflow, and delete action

### 15. M3 — Maintenance page bulk re-tag — applied 2026-04-05

- Added `GET /api/maintenance/retag-preview` with filters by category, tag, status, and max records
- Added `GET /api/maintenance/retag-run` SSE endpoint for batch AI re-generation of alt text and/or tags
- Bulk re-tag supports both local and SharePoint image loading with High-Res/WebP/legacy fallbacks
- Successful processed records are reset to `pending-review` for sign-off
- Added Bulk Re-Tag section in Maintenance UI with preview, run controls, live progress log, and summary output

### 14. M2 — Maintenance page duplicate detector — applied 2026-04-05

- Added `GET /api/maintenance/duplicates` to detect duplicate groups by filename, slug, exact alt text, and optional near-alt similarity
- Added `POST /api/maintenance/duplicates/resolve` with `action=merge|delete`, keeper selection, and `confirm_token=PURGE`
- Merge action consolidates tags, chooses a stronger alt text, fills missing core fields on the keeper, then deletes extra records
- Added Duplicate Detector section in Maintenance UI with scan controls, grouped result list, keeper selector, and resolve action

### 13. M1 — Maintenance page orphan file finder — applied 2026-04-05

- Added `GET /api/maintenance/orphans` to compare metadata records vs storage files in both directions
- Scan output includes missing-file records plus orphaned WebP/High-Res files for both local and SharePoint modes
- Added `POST /api/maintenance/orphans/delete-records` to bulk-delete orphaned records with `confirm_token=PURGE`
- Added `POST /api/maintenance/orphans/flag-missing` to add a `?missing-file` tag and optionally reset status to `pending-review`
- Added Orphan Finder section in Maintenance UI with scan, flag, and delete actions

### 12. M7 — Maintenance page record purge by status — applied 2026-04-05

- Added `GET /api/maintenance/purge-preview` for safe preflight count by status (`rejected` / `archived`)
- Added `POST /api/maintenance/purge-status` with explicit `confirm_token=PURGE` and stale preview count protection
- Added optional file deletion for both local (`IMAGE_FOLDER/WebP` + `IMAGE_FOLDER/High-Res`) and SharePoint (`Images/WebP` + `Images/High-Res`) paths
- Added safe path sanitization and traversal checks before local deletion
- Added maintenance UI controls for preview-first purge, confirmation modal, and structured result reporting

### 11. M8 — High-Res source folders + maintenance sync utility — applied 2026-04-05

- High-Res storage is source-based: `High-Res/{source}/...`; WebP remains category-based under `WebP/{category}/...`
- Added canonical `Source` field support in both metadata clients (`LocalClient` and `SharePointListClient`)
- Updated stock catalog and upload processing to write source-aware metadata and High-Res paths
- Updated `ImageScanner` and `src/main.py` to scan `IMAGE_FOLDER/High-Res` source trees
- Added `/maintenance` page and `/api/maintenance/sync-highres` SSE utility
- Sync utility supports dry-run, catalogs unprocessed High-Res files, and reports orphaned WebP files
- Added maintenance link to the home header navigation

### 10. M9 — Remove all Airtable references — applied 2026-04-05

- Deleted `src/airtable_client.py`
- Replaced live-path Airtable imports in `src/app.py` (`run_clean`, `api_preview`) with `SharePointListClient`
- Renamed legacy `run_scan_airtable` route to `run_scan_live`
- Updated source/doc wording in `src/main.py`, `src/local_client.py`, `src/sharepoint_list_client.py`, `src/sharepoint_client.py`, `src/config.py`, `src/__init__.py`
- Updated documentation references in `specification.md`, `development.md`, and `.github/copilot-instructions.md`
- Verified no remaining Airtable references in source files and canonical docs

### 9. Local-ready setup + production auth-bypass guardrail — applied 2026-04-05

- Added `DEV_AUTH_BYPASS` config with local-safe default behavior in TEST_MODE
- Added runtime guardrail: app/CLI now fail fast if `DEV_AUTH_BYPASS=true` while `TEST_MODE=false`
- Added `@login_required` to previously open API/utility routes (`/api/images`, tag-library writes, upload stage/process, `/run/*`)
- Updated VS Code tasks to run via `.venv/bin/python3` and local-safe env flags
- Added `pytest` to `requirements.txt` for consistent local test execution
- Updated local docs (`README.md`, `development.md`, `.env.example`) with the validated local workflow

### 1. Search-first home screen + welcome modal — applied 2026-04-05

- Hero view: gradient section with large centered search bar, "Browse by category" tile grid, "Recently added" horizontal strip
- Browse view: appears after search/category click; has compact header search, sidebar, tag strip, grid
- "← Home" back button returns to hero and clears all filters
- Welcome modal: shows on first visit (localStorage), dismissed with "Got it"; re-opens from "?" button; updated copy

### 8. Align local and SharePoint folder structures — applied 2026-04-04

- `image_processor.py` local store path changed to `IMAGE_FOLDER/WebP/{category}/{file}` (matches SP convention)
- `_serve_image` local: tries `WebP/{location}` first, falls back to `{location}` for legacy pre-migration records
- Location field convention unchanged: `{category}/{file}` without WebP/ prefix in both modes

### 7. MCP tool: `catalog_image_from_file` — applied 2026-04-04

- New MCP tool accepts `image_data` (base64), `filename`, `category`
- Decodes bytes → runs full `process_image` pipeline → returns slug/alt_text/tags
- `Project-Instructions.md`: replaced manual upload redirect with direct tool usage

### 6. Image review workflow — applied 2026-04-04

- `patch_fields(record_id, fields)` added to both `LocalClient` and `SharePointListClient`
- `GET /api/images` now includes `status` field and accepts `?status=` filter param
- `GET /api/pending-count` returns count of `pending-review` records
- `PATCH /api/image-status` updates status (+ optional alt_text) on a record
- `GET /review` route + `templates/review.html`: queue of pending images with editable alt text, Approve/Reject/Archive buttons
- `templates/index.html`: Review nav link with amber pending count badge; status color dots on image cards

### 5. Hybrid metadata for stock downloads — applied 2026-04-04

- `process_image` now accepts `source_context` passed as `context` to Claude alt-text/tag calls
- `_stock_source_context()` helper builds context from title/tags/photographer
- `/api/catalog-stock` SSE endpoint downloads + processes with source context
- Download modal: "Download" saves to disk; "Add to Library" streams catalog progress

### 4. Increase stock search results per library — applied 2026-04-04

- Default raised from 8 → 12, cap from 12 → 20 in `src/app.py` and `templates/stock_search.html`

### 3. Increase Shutterstock modal thumbnail size — applied 2026-04-04

- `#ss-preview` now full-width (100%, max-height 220px); `#ss-img-section` stacks column

### 2. Thumbnail URL caching — applied 2026-04-04

- `_sp_url_cache` dict in `src/app.py` caches SharePoint CDN URLs with 45-min TTL via `_get_sp_url()`

### Add `/health` endpoint — deployed 2026-04-05
