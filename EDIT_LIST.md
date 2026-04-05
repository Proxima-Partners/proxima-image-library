# Edit List

Pending changes — rebuild only on approval.

---

## Pending

### Delete webflow/ directory

- Remove `webflow/library.html`, `webflow/maintenance.html`, `webflow/stock-search.html`, `webflow/upload.html`
- Webflow integration removed; templates no longer used or maintained

---

## Future Development Queue

### M1. Maintenance page — Orphan file finder

- Compare image files on disk to records in the library (and vice versa)
- Surface files with no record and records with no file
- Both `LocalClient` and `SharePointListClient` implementations
- UI: table of mismatches with option to delete orphaned records or flag missing files

### M2. Maintenance page — Duplicate detector

- Find records with identical filenames, slugs, or near-identical alt text
- Useful after multiple scan runs
- UI: grouped list of duplicates with option to delete/merge

### M3. Maintenance page — Bulk re-tag

- Select records by category, tag, or status filter
- Re-run Claude vision on selected images to regenerate alt text and/or tags
- Streams progress via SSE; results land in `pending-review` for human sign-off
- Useful when tag vocabulary changes

### M4. Maintenance page — Broken thumbnail checker

- Scan all records and attempt to load each image file
- Flag records where the file is missing, unreadable, or corrupt
- UI: list of broken records with option to delete or re-link

### M5. Maintenance page — Status reset

- Bulk-set a filtered set of records back to `pending-review`
- Filters: by category, tag, current status, or date range
- Confirmation step before applying
- Useful for re-reviewing after vocabulary or policy changes

### M6. Maintenance page — Export to CSV

- Download full library as CSV (id, filename, category, alt text, tags, status, location)
- Optional filter by category or status before export
- Useful for audits or bulk edits in Excel

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
- Downloaded image lands in correct High-Res source folder (post-M8)

**MCP tools (Claude Desktop):**

- `search_image_library` returns results for a known keyword
- `catalog_image_from_file` processes a base64 image and creates a pending-review record
- MCP server survives Claude Desktop restart without path errors

**Tag manager:**

- Add, remove, promote tags
- Promoted tags appear in search filter
- Changes persist across server restart

**Maintenance utilities (post-M1–M9):**

- Each utility completes without error in TEST_MODE
- Orphan finder correctly identifies staged test orphans
- CSV export produces valid file with all fields

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

- Remove `src/airtable_client.py` and all remaining Airtable imports (see M9)
- Audit all `@app.route` endpoints — identify any that are unreachable or no longer wired to a UI
- Remove commented-out code blocks throughout `src/app.py`, `src/image_processor.py`, `src/mcp_server.py`
- Check `src/__init__.py` for stale imports
- Identify any template files with no corresponding route
- Check `static/` for unused CSS, JS, or image assets

**Redundancy:**

- Review `LocalClient` and `SharePointListClient` for duplicate logic that should be in a shared base class or helper
- Audit `src/app.py` for repeated patterns (e.g. `get_client()` calls, error response formatting) that should be factored into helpers
- Check for duplicate route logic between `/run/scan-test` and `/run/scan-airtable`
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

### W1. End-to-end test: Proxima Writing → Image Library → Webflow CMS

Test the full writing workflow from Claude through to published content:

**Skills (proxima-claude-org-skills):**

- Invoke Blog Writing, Article Writing skills via Claude
- Confirm Branding Skill is correctly inherited as base in all writing skills
- Verify photo suggestion phrases are extracted and passed to Image Library MCP

**MCP integration:**

- `search_image_library` tool returns ranked results from the library
- `catalog_image_from_file` tool correctly processes a dropped image end-to-end
- Confirm MCP server loads correctly in Claude Desktop (absolute paths, `.env` sourced)

**CMS push:**

- Selected images and written content pushed to Webflow CMS collection items
- Verify field mapping: title, body, author, image, slug, tags
- Confirm published state and staging vs. live behavior

**Acceptance criteria:**

- Full run from blank prompt → finished article → Webflow CMS item with image, no manual steps
- Review queue receives any newly cataloged images from the session

### M9. Remove all Airtable references

- Delete `src/airtable_client.py` (replaced by `SharePointListClient` + `LocalClient`)
- Audit and update 13 files that contain Airtable references:
  `src/app.py`, `src/local_client.py`, `src/sharepoint_list_client.py`, `src/main.py`,
  `src/sharepoint_client.py`, `src/config.py`, `src/__init__.py`,
  `development.md`, `README.md`, `specification.md`, `.github/copilot-instructions.md`
- Replace `AirtableClient` references in code with `SharePointListClient` or `LocalClient` as appropriate
- Update all docs to remove mention of Airtable as a backend option
- Verify no imports of `airtable_client` remain

### M8. High-Res directory — source-based folders + WebP sync utility

**Directory restructure:**

- High-Res local folder uses source-based subfolders instead of category: `IMAGE_FOLDER/High-Res/{source}/{file}`
- Sources: `ShutterStock`, `AdobeStock`, `Unsplash`, `Pexels`, `Pixabay`, `Internal`
- WebP directory keeps existing category-based structure: `IMAGE_FOLDER/WebP/{category}/{file}`
- Source is stored as a new `Source` field on the library record

**Sync utility (maintenance page):**

- Scan all High-Res source folders for image files
- Identify files that have no matching library record (user-dropped files, direct copies)
- For each unprocessed file: convert to WebP → run Claude metadata pipeline → create record with `status=pending-review`
- Also detect WebP files with no corresponding High-Res original (orphaned WebP) and flag them
- Streams progress via SSE; summary report at completion
- Both `LocalClient` and `SharePointListClient` implementations

**Download flow update:**

- Stock downloads (Shutterstock, Pexels, etc.) save original to `High-Res/{source}/` in addition to WebP
- `catalog-stock` SSE endpoint updated to write High-Res copy alongside WebP

**Scan/reindex update:**

- `ImageScanner` / `src/main.py` updated to walk `High-Res/{source}/` folders when building the new-files list

### M7. Maintenance page — Record purge by status

- Bulk-delete all `rejected` or `archived` records
- Option to also delete the associated image files from disk/SharePoint
- Confirmation modal showing record count before executing
- Both `LocalClient` and `SharePointListClient` implementations

---

## Applied

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
