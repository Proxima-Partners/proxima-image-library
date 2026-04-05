# Proxima Image Library

AI-powered image asset management for Proxima. Scans a local image folder, generates alt text and tags via Claude vision, syncs metadata to a SharePoint List, and provides a web UI for browsing, stock photo search, and download.

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
flask --app src.app run --port 5000 --debug
```

`.env` must have `TEST_MODE=true` and `STORAGE_MODE=local`.

**Live (SharePoint backend):**

```bash
source .venv/bin/activate
flask --app src.app run --port 5000
```

Open **[http://localhost:5000](http://localhost:5000)** — login via Microsoft/MSAL on first visit.

Minimum `.env` for dev: `ANTHROPIC_API_KEY`, `IMAGE_FOLDER`, `TEST_MODE=true`, `STORAGE_MODE=local`, `FLASK_SECRET_KEY`, MSAL vars.
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
├── airtable_client.py          Airtable CRUD (legacy — not used in current stack)
├── image_scanner.py            Recursive image discovery
├── tag_library.py              Tag vocabulary management
├── config.py                   Env var loading and Config object
├── mcp_server.py               MCP server — search_image_library, search_stock_photos, catalog_stock_image
├── rename_assets.py            Batch rename to {prefix}-{slug}.{ext}
└── stock_client.py             Pexels / Shutterstock / Unsplash / Pixabay search + full metadata

templates/                      Jinja2 HTML — library browser, stock search, upload, tag manager, review
tests/                          pytest — rename_assets, ImageScanner
test_data/                      local_table.json — 253 records for local dev/testing
```

`LocalClient` and `SharePointListClient` share identical interfaces. `TEST_MODE=true` swaps between them with zero code changes.

---

## Key Commands

| Task | Command |
| ---- | ------- |
| Start server (dev) | `flask --app src.app run --port 5000 --debug` |
| Start server (live) | `flask --app src.app run --port 5000` |
| Run tests | `pytest` |
| Sync images to SharePoint | `python3 -u -m src.main` |
| Rename images (preview) | `python3 -m src.rename_assets --prefix proxima` |
| Rename images (apply) | `python3 -m src.rename_assets --prefix proxima --apply` |

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

---

## Documentation

| Document | Contents |
| -------- | -------- |
| [development.md](development.md) | Setup, architecture, how-to guides, code conventions, gotchas |
| [specification.md](specification.md) | Image output targets, naming, SharePoint List schema, AI metadata spec |
| [search-parameter.md](search-parameter.md) | Stock photo API parameters, auth, attribution requirements |
| [project-scope.md](project-scope.md) | Feature definitions and application parameters |
| [EDIT_LIST.md](EDIT_LIST.md) | Pending and applied changes — build only on approval |
| [PRODUCTION_DEPLOY.md](PRODUCTION_DEPLOY.md) | Deployment checklist for Azure App Service |
