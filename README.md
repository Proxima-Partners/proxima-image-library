# Proxima Image Library

AI-powered image asset management for Proxima. Scans a local image folder, generates alt text and tags via Claude vision, syncs metadata to Airtable, and provides a web UI for browsing and stock photo search.

**Tech stack:** Python 3 · Flask · Claude `claude-sonnet-4-6` · SharePoint List · Pillow · Vanilla HTML/CSS/JS

---

## Quick Start

```bash
pip3 install -r requirements.txt
cp .env.example .env        # fill in keys and IMAGE_FOLDER
```

**Development (no Airtable required):**

```bash
TEST_MODE=true python3 -m flask --app src.app run --port 5000
```

**Live:**

```bash
python3 -m flask --app src.app run --port 5000
```

Open **http://localhost:5000**

Minimum `.env` for dev: `ANTHROPIC_API_KEY`, `IMAGE_FOLDER`, `TEST_MODE=true`
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
├── airtable_client.py          Airtable CRUD (legacy)
├── image_scanner.py            Recursive image discovery
├── tag_library.py              Tag vocabulary management
├── config.py                   Env var validation
├── mcp_server.py               MCP server — search_image_library, search_stock_photos, catalog_stock_image
├── rename_assets.py            Batch rename to {prefix}-{slug}.{ext}
└── stock_client.py             Pexels / Shutterstock / Unsplash / Pixabay search

templates/                      Jinja2 HTML — library browser, stock search, upload, tag manager
tests/                          pytest — rename_assets, ImageScanner
```

`LocalClient` and `SharePointListClient` share identical interfaces. `TEST_MODE=true` swaps between them with zero code changes.

---

## Key Commands

| Task | Command |
| ---- | ------- |
| Start server (dev) | `TEST_MODE=true python3 -m flask --app src.app run --port 5000` |
| Start server (live) | `python3 -m flask --app src.app run --port 5000` |
| Run tests | `pytest` |
| Sync images to SharePoint | `python3 -u -m src.main` |
| Rename images (preview) | `python3 -m src.rename_assets --prefix proxima` |
| Rename images (apply) | `python3 -m src.rename_assets --prefix proxima --apply` |

---

## Documentation

| Document | Contents |
| -------- | -------- |
| [development.md](development.md) | Setup, architecture, how-to guides, code conventions, gotchas |
| [specification.md](specification.md) | Image output targets, naming, SharePoint List schema, AI metadata spec |
| [search-parameter.md](search-parameter.md) | Stock photo API parameters, auth, attribution requirements |
| [project-scope.md](project-scope.md) | Feature definitions and application parameters |
