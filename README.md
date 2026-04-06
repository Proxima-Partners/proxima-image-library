# Proxima Image Library

AI-powered image asset management for Proxima. Scans a local image folder, generates alt text and tags via Claude vision, syncs metadata to a SharePoint List, and provides a web UI for browsing, stock photo search, image review, and download.

**Tech stack:** Python 3 · Flask · Claude `claude-sonnet-4-6` · SharePoint List · Microsoft Graph API · MSAL · Pillow · Vanilla HTML/CSS/JS

---

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in keys and IMAGE_FOLDER
```

**Development (local data, no SharePoint required):**

```bash
source .venv/bin/activate
TEST_MODE=true STORAGE_MODE=local DEV_AUTH_BYPASS=true .venv/bin/python3 -m flask --app src.app run --port 5000 --debug
```

`.env` should have `TEST_MODE=true` and `STORAGE_MODE=local`.
Set `DEV_AUTH_BYPASS=true` to skip Microsoft login in local TEST_MODE.

To test real Microsoft auth locally, run with `DEV_AUTH_BYPASS=false` and use
`http://localhost:5000` consistently for login/callback. Do not mix
`localhost` and `127.0.0.1` during the same auth flow.

**Live (SharePoint backend):**

```bash
source .venv/bin/activate
flask --app src.app run --port 5000
```

Open **[http://localhost:5000](http://localhost:5000)** — login via Microsoft/MSAL on first visit.

When `DEV_AUTH_BYPASS=true` in TEST_MODE, the app auto-authenticates a local session and opens directly.

Minimum `.env` for dev: `ANTHROPIC_API_KEY`, `IMAGE_FOLDER`, `TEST_MODE=true`, `STORAGE_MODE=local`, `FLASK_SECRET_KEY`.
Optional for local login bypass: `DEV_AUTH_BYPASS=true`.
MSAL vars are required when testing real auth flow or running live mode.
Full setup: see [development.md](development.md#environment-variables-reference)

---

## Project Structure

```text
src/
├── app.py                      Flask routes, thumbnail serving, SSE streaming
├── main.py                     CLI scan → generate → upload pipeline
├── ai_generator.py             Claude vision — alt text + tags
├── image_processor.py          Upload/stock image processing pipeline
├── sharepoint_list_client.py   SharePoint List CRUD (live mode)
├── sharepoint_client.py        SharePoint file operations via Graph API
├── local_client.py             Local JSON store, same interface (TEST_MODE)
├── image_scanner.py            Recursive image discovery
├── tag_library.py              Tag vocabulary management
├── config.py                   Env var loading and Config object
├── mcp_server.py               MCP server — search_image_library, search_stock_photos, catalog_image_from_file
├── rename_assets.py            Batch rename to {prefix}-{slug}.{ext}
└── stock_client.py             Pexels / Shutterstock / Unsplash / Pixabay search + full metadata

templates/
├── index.html                  Search-first library browser — hero, category tiles, browse grid
├── maintenance.html            Admin maintenance console — M1–M8 + M10–M20 operations
├── stock_search.html           Stock photo search — phrase chips → results grid → download modal
├── review.html                 Review queue — approve/reject/archive pending images
├── upload.html                 Image upload and catalog pipeline with SSE progress
├── tag_manager.html            Tag vocabulary editor
└── login_error.html            Access denied/error template

tests/                          pytest — rename_assets, ImageScanner
test_data/                      local_table.json — 253 records for local dev/testing
```

`LocalClient` and `SharePointListClient` share identical interfaces. `TEST_MODE=true` swaps between them with zero code changes.

---

## Key Commands

| Task | Command |
| ---- | ------- |
| Start server (dev) | `TEST_MODE=true STORAGE_MODE=local DEV_AUTH_BYPASS=true .venv/bin/python3 -m flask --app src.app run --port 5000 --debug` |
| Start server (dev auth required) | `TEST_MODE=true STORAGE_MODE=local DEV_AUTH_BYPASS=false .venv/bin/python3 -m flask --app src.app run --port 5000` |
| Start server (live) | `.venv/bin/python3 -m flask --app src.app run --port 5000` |
| Run tests | `.venv/bin/python3 -m pytest -v` |
| Run automated T1 suite | `.venv/bin/python3 scripts/run_t1_suite.py` |
| Sync images to SharePoint | `.venv/bin/python3 -u -m src.main` |
| Rename images (preview) | `.venv/bin/python3 -m src.rename_assets --prefix proxima` |
| Rename images (apply) | `.venv/bin/python3 -m src.rename_assets --prefix proxima --apply` |

### Maintenance Access

- `/maintenance` and `/api/maintenance/*` are admin-gated in normal auth mode.
- Set `MAINTENANCE_ADMIN_USERS` to a comma-separated allowlist of emails/UPNs.
- In local TEST mode only, `DEV_AUTH_BYPASS=true` allows bypass login for faster iteration.

### Auth Session Validation (TEST_MODE only)

- Session expiry is enforced from the MSAL `exp` claim.
- Local auth testing helper endpoint: `POST /auth/test-expire-session`
  - available only when `TEST_MODE=true`
  - marks current session expired for deterministic manual testing
  - returns redirect to `/login` when not authenticated

---

## MCP Server (Claude Desktop integration)

Register in `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "proxima-image-library": {
      "command": "/Users/mike-j4c/Projects/proxima-image-library/.venv/bin/python3",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/Users/mike-j4c/Projects/proxima-image-library",
      "env": {
        "PYTHONPATH": "/Users/mike-j4c/Projects/proxima-image-library",
        "TEST_MODE": "true",
        "STORAGE_MODE": "local"
      }
    }
  }
}
```

`TEST_MODE` and `STORAGE_MODE` are set explicitly here because Claude Desktop may not load `.env` from `cwd` reliably.

### MCP Tools

| Tool | Description |
| ---- | ----------- |
| `search_image_library` | Search the image library by keyword; returns ranked results with thumbnails |
| `search_stock_photos` | Search Pexels, Shutterstock, Unsplash, Pixabay concurrently |
| `catalog_image_from_file` | Accept a base64 image, run the full processing pipeline, add to library |

---

## Documentation

| Document | Contents |
| -------- | -------- |
| [development.md](development.md) | Setup, architecture, how-to guides, code conventions, gotchas |
| [specification.md](specification.md) | Image output targets, naming, SharePoint List schema, AI metadata spec |
| [search-parameter.md](search-parameter.md) | Stock photo API parameters, auth, attribution requirements |
| [project-scope.md](project-scope.md) | Feature definitions, application parameters, and developer onboarding (including guidance for developers using OpenAI-based coding tools) |
| [EDIT_LIST.md](EDIT_LIST.md) | Applied changes and active future development queue |
| [PRODUCTION_DEPLOY.md](PRODUCTION_DEPLOY.md) | Deployment checklist for Azure App Service |
