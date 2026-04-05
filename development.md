# Development Workflow

How to set up, run, modify, and extend the Proxima Image Library app.

---

## Prerequisites

| Requirement | Version | Notes |
| ----------- | ------- | ----- |
| Python | 3.10+ | Check with `python3 --version` |
| pip | current | Bundled with Python |
| Anthropic API key | — | Required for AI alt text and tags |
| Azure AD app registration | — | Required for MSAL auth and SharePoint (live mode only) |

Optional (stock photo search):

| Requirement | Notes |
| ----------- | ----- |
| Pexels API key | Free at pexels.com/api |
| Shutterstock client ID + secret | Free dev tier at shutterstock.com/developers |
| Unsplash access key | Free at unsplash.com/developers |
| Pixabay API key | Free at pixabay.com/api/docs |

---

## Initial Setup

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd proxima-image-library

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — minimum dev keys listed below
```

**Minimum `.env` for development (local data, no SharePoint):**

```bash
ANTHROPIC_API_KEY=sk-ant-...
IMAGE_FOLDER=/absolute/path/to/your/images
TEST_MODE=true
STORAGE_MODE=local
FLASK_SECRET_KEY=any-random-string
MSAL_CLIENT_ID=<azure-app-client-id>
MSAL_CLIENT_SECRET=<azure-app-client-secret>
MSAL_TENANT_ID=<azure-tenant-id>
MSAL_REDIRECT_URI=http://localhost:5000/auth/callback
```

`TEST_MODE=true` uses `test_data/local_table.json` instead of SharePoint List.
`STORAGE_MODE=local` serves image files from `IMAGE_FOLDER` instead of SharePoint.

**Full `.env` for live SharePoint mode:** see [PRODUCTION_DEPLOY.md](PRODUCTION_DEPLOY.md).

---

## Running the App

**Development (local data — safe, no SharePoint writes):**

```bash
source .venv/bin/activate
flask --app src.app run --port 5000 --debug
```

**Live (writes to SharePoint):**

```bash
source .venv/bin/activate
flask --app src.app run --port 5000
```

Open [http://localhost:5000](http://localhost:5000) — first visit redirects to Microsoft login via MSAL.

> If port 5000 is in use on macOS, disable **AirPlay Receiver** in System Settings → General → AirDrop & Handoff.
> **Important:** Always restart Flask after changing `.env`. The running process does not reload environment variables on file change — only code changes trigger the reloader.

---

## MCP Server (Claude Desktop Integration)

The MCP server exposes three tools so Claude Desktop can search images and catalog stock photos inline during writing sessions.

### Tools

| Tool | Trigger | Description |
| ---- | ------- | ----------- |
| `search_image_library` | Auto — after blog/article skill output | Searches local JSON or SharePoint List; returns ranked matches with inline thumbnails |
| `search_stock_photos` | After internal search returns no selection | Searches Pexels, Shutterstock, Unsplash, Pixabay concurrently; returns inline thumbnails |
| `catalog_image_from_file` | When user drops a file directly into Claude | Accepts base64 image data, runs full processing pipeline, adds record to library |

### Register in Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

`TEST_MODE` and `STORAGE_MODE` must be set explicitly in `env` here — Claude Desktop may not correctly load `.env` from `cwd` when launching the server (shell environment extraction can fail on macOS).

Restart Claude Desktop after editing the config.

### MCP server path requirements

The MCP server uses absolute paths anchored to `__file__` — do not change to relative paths:

- `load_dotenv(Path(__file__).parent.parent / ".env")` — loads `.env` from project root
- `_DEFAULT_PATH = Path(__file__).parent.parent / "test_data" / "local_table.json"` — finds local data regardless of cwd

### Troubleshooting MCP tools not loading

Check `~/Library/Logs/Claude/mcp-server-proxima-image-library.log` and `main.log`.

Common issue: Claude Desktop's utility process crashes on startup (logged as `'Utility' process exited with 'abnormal-exit'`). This is a Desktop-side issue caused by shell environment extraction failure — often triggered by slow `.zshrc` initialization. Add to the top of `~/.zshrc`:

```zsh
[[ $- != *i* ]] && return
```

This exits `.zshrc` immediately for non-interactive shells (which is what Desktop uses for env extraction).

---

## Running Tests

```bash
pytest
# or
pytest -v
pytest tests/test_rename_assets.py
```

Tests live in `tests/` and use `pytest`. No `.env` required — tests instantiate modules directly with `tmp_path` fixtures and do not call any external APIs.

---

## Architecture Overview

```text
src/
├── app.py                    Flask routes and server — web UI entry point
├── main.py                   CLI orchestrator — scan → generate → upload pipeline
├── ai_generator.py           Claude vision API — alt text (125 chars max) and tags
├── sharepoint_list_client.py SharePoint List CRUD — live metadata store
├── sharepoint_client.py      SharePoint file operations via Microsoft Graph API
├── local_client.py           Drop-in local JSON store — identical interface (TEST_MODE)
├── image_processor.py        Upload/stock image processing pipeline
├── image_scanner.py          Recursive image discovery via Path.rglob()
├── mcp_server.py             MCP stdio server — search_image_library, search_stock_photos, catalog_image_from_file
├── config.py                 Env var loading and Config object
├── rename_assets.py          Batch rename to {prefix}-{slug}.{ext} format
├── stock_client.py           Pexels / Shutterstock / Unsplash / Pixabay — full metadata
└── tag_library.py            Tag vocabulary management

templates/
├── index.html                Search-first library browser — hero, category tiles, browse grid
├── stock_search.html         Stock photo search — phrase chips → results grid → download modal
├── review.html               Review queue — approve/reject/archive pending images with badge count
├── upload.html               Image upload and catalog pipeline with SSE progress
└── tag_manager.html          Tag vocabulary editor

test_data/
└── local_table.json          253 records for local dev/testing (mirrors SharePoint List schema)
```

### Dual-backend pattern

`SharePointListClient` (live) and `LocalClient` (test) share identical method signatures. `TEST_MODE=true` swaps one for the other — no code changes needed. All new data-layer features must be implemented in **both** clients.

```text
TEST_MODE=true  →  LocalClient            →  test_data/local_table.json
TEST_MODE=false →  SharePointListClient   →  SharePoint List (Microsoft Graph API)
```

### Storage modes

`STORAGE_MODE` controls where image files are served from — independent of `TEST_MODE`:

```text
STORAGE_MODE=local       →  serves JPEG thumbnails from IMAGE_FOLDER via PIL
STORAGE_MODE=sharepoint  →  redirects to SharePoint CDN URL via Graph API
```

For local dev use both `TEST_MODE=true` and `STORAGE_MODE=local`.

---

## How To: Common Tasks

### Add a Flask route

1. Add the route function to [src/app.py](src/app.py)
2. If it returns HTML, add a template to `templates/`
3. If it's an API endpoint, return `jsonify(...)` with a consistent shape

```python
@app.route("/my-feature")
@login_required
def my_feature():
    return render_template("my_feature.html")

@app.route("/api/my-data", methods=["POST"])
def api_my_data():
    data = request.get_json(force=True)
    return jsonify({"result": ...})
```

Security checklist for new routes:

- Never construct file paths from user input without resolving and checking against `IMAGE_FOLDER`
- Use `unquote()` on URL-encoded path parameters before resolving
- Validate at the boundary — trust nothing from `request`

### Add a new SharePoint List field

1. Add the column to the SharePoint List manually (SharePoint UI)
2. Update `create_record()` and `update_record()` in **both** [src/sharepoint_list_client.py](src/sharepoint_list_client.py) and [src/local_client.py](src/local_client.py)
3. Update the schema table in [specification.md](specification.md)

### Add a new AI-generated field

1. Add a `generate_<field>()` method to the generator class in [src/ai_generator.py](src/ai_generator.py)
2. Call it in the pipeline alongside the existing `generate_alt_text()` / `generate_tags()` calls
3. Pass the result to `create_record()` (SharePoint field must exist first — see above)

Keep the model pinned to `claude-sonnet-4-6`. Do not change it without discussion.

### Add a new stock photo API

1. Add a `search_<name>(phrase, limit)` function to [src/stock_client.py](src/stock_client.py) returning `{"results": [...], "error": str|None}`
2. Each result dict must include at minimum: `thumb`, `title`, `link`, plus all available metadata fields
3. Add the searcher to `search_all_libraries()` in `stock_client.py`
4. Add the new tab to the `LIBS` array in `templates/stock_search.html`
5. Document the API in [search-parameter.md](search-parameter.md)

---

## Code Conventions

| Convention | Rule |
| ---------- | ---- |
| AI model | Always `claude-sonnet-4-6` — do not change without discussion |
| Data layer | Every new feature uses the dual-backend pattern — implement in both clients |
| Path handling | Always resolve paths and validate against `IMAGE_FOLDER` before serving files |
| MCP server paths | Always use absolute paths anchored to `__file__` — never relative paths |
| Status values | SharePoint Status field uses hyphens: `pending-review`, `approved`, `rejected`, `archived` |
| File naming | New image files follow `{prefix}-{slug}.{ext}` — see [specification.md](specification.md) |
| Tag vocabulary | Tags drawn from predefined list in [specification.md](specification.md) — do not invent new tags in code |
| Alt text | Max 125 characters; no "Image of" or "Picture of" prefix |

---

## Environment Variables Reference

| Variable | Required | Default | Description |
| -------- | -------- | ------- | ----------- |
| `ANTHROPIC_API_KEY` | Always | — | Claude API key |
| `IMAGE_FOLDER` | Always | `./assets` | Absolute path to local image directory |
| `TEST_MODE` | No | `false` | `true` uses LocalClient (local JSON) instead of SharePoint List |
| `STORAGE_MODE` | No | `local` | `local` serves files from IMAGE_FOLDER; `sharepoint` redirects to SharePoint CDN |
| `FLASK_SECRET_KEY` | Always | — | Flask session signing key — use a random 32+ byte hex string |
| `MSAL_CLIENT_ID` | Always | — | Azure app registration client ID |
| `MSAL_CLIENT_SECRET` | Always | — | Azure app registration client secret |
| `MSAL_TENANT_ID` | Always | — | Azure tenant ID |
| `MSAL_REDIRECT_URI` | Always | `http://localhost:5000/auth/callback` | Must match Azure app redirect URI |
| `SHAREPOINT_TENANT_ID` | Live mode | — | SharePoint tenant ID |
| `SHAREPOINT_CLIENT_ID` | Live mode | — | SharePoint app client ID |
| `SHAREPOINT_CLIENT_SECRET` | Live mode | — | SharePoint app client secret |
| `SHAREPOINT_SITE_ID` | Live mode | — | SharePoint site ID |
| `SHAREPOINT_DRIVE_ID` | Live mode | — | SharePoint document library drive ID |
| `SHAREPOINT_LIST_NAME` | Live mode | `Assets` | SharePoint List name |
| `SHAREPOINT_IMAGE_FOLDER` | Live mode | `Images` | SharePoint folder root for image files |
| `SUPPORTED_FORMATS` | No | `.jpg,.jpeg,.png,.gif,.webp` | Comma-separated extensions |
| `CORS_ORIGINS` | No | `http://localhost:5000` | Comma-separated allowed CORS origins |
| `PEXELS_API_KEY` | Stock search | — | Pexels API key |
| `SHUTTERSTOCK_CLIENT_ID` | Stock search | — | Shutterstock app client ID |
| `SHUTTERSTOCK_CLIENT_SECRET` | Stock search | — | Shutterstock app client secret |
| `UNSPLASH_ACCESS_KEY` | Stock search | — | Unsplash access key |
| `PIXABAY_API_KEY` | Stock search | — | Pixabay API key |

---

## Known Issues and Gotchas

| Issue | Cause | Fix / Workaround |
| ----- | ----- | ---------------- |
| Thumbnails not showing after Flask restart | Running process doesn't reload `.env` on code-only restart | Always kill and restart Flask after `.env` changes |
| MCP tools not loading in Claude Desktop | Desktop utility process crashes on shell env extraction | Add `[[ $- != *i* ]] && return` to top of `~/.zshrc`; also set `TEST_MODE`/`STORAGE_MODE` explicitly in Desktop MCP config `env` block |
| MCP server read-only filesystem error | `LocalClient` or `load_dotenv` using relative paths, resolving to a non-writable directory | MCP server must use absolute paths anchored to `__file__` — never relative paths |
| Port 5000 in use | macOS AirPlay Receiver | System Settings → General → AirDrop & Handoff → disable AirPlay Receiver |
| Stock search tab shows "not configured" | Missing env var | Add the relevant API key(s) to `.env` |
| Thumbnail returns 500 | Image format unreadable by Pillow (e.g. CMYK JPEG) | Convert source image to sRGB before adding to `IMAGE_FOLDER` |
| `build_plan` re-renames already-named files | Slug derived from full stem including prefix | Run rename once per batch — re-running is safe but will double-prefix |
| `local_table.json` corrupt after concurrent writes | Concurrent PATCH requests (e.g. Approve All) all read-modify-write simultaneously | Fixed: `LocalClient._save()` uses atomic write (`.tmp` + rename) and `_LOCK` threading lock — serialises all reads/writes |
| Review badge count stale after approving | `get_all_records()` 5-minute cache not invalidated on status change | Fixed: `api_image_status` sets `_records_cache = None` on every successful PATCH |

---

## Next Steps

### Production deployment

See [PRODUCTION_DEPLOY.md](PRODUCTION_DEPLOY.md) for the full Azure App Service checklist. Complete T1 (pre-production test protocol) and T2 (security audit) before deploying.

### Writing skills integration

The Proxima Writing Claude Desktop project uses the MCP server tools. After any change to the writing skills:

1. Run `./build-skills.sh` in the skills repo (or it runs automatically via pre-commit hook)
2. Upload the new `proxima-skills.zip` to the Claude Project knowledge files
3. If `Project-Instructions.md` changed, update the Proxima Writing system prompt

### Future development queue

See [EDIT_LIST.md](EDIT_LIST.md) for the full queue. Key upcoming items:

- **M1–M7** — Maintenance utilities (orphan finder, duplicate detector, bulk re-tag, export, purge)
- **M8** — High-Res source-based folder structure + WebP sync utility
- **M9** — Remove all remaining Airtable references
- **T1** — Comprehensive pre-production test protocol
- **T2** — Security audit checklist
- **T3** — Full code audit (unused code, redundancy, latency, conventions)
- **W1** — End-to-end test: Proxima Writing → Image Library → Webflow CMS

---

## Reference Documents

| Document | Purpose |
| -------- | ------- |
| [project-scope.md](project-scope.md) | Feature definitions, workflows, application parameters |
| [specification.md](specification.md) | Image output targets, naming convention, SharePoint List schema, AI metadata spec |
| [search-parameter.md](search-parameter.md) | Stock photo API parameters, authentication, attribution requirements |
| [EDIT_LIST.md](EDIT_LIST.md) | Pending and applied changes — build only on approval |
| [PRODUCTION_DEPLOY.md](PRODUCTION_DEPLOY.md) | Azure deployment checklist |
| [README.md](README.md) | Quick start and end-user reference |
