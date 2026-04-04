# Development Workflow

How to set up, run, modify, and extend the Proxima Image Library app.

---

## Prerequisites

| Requirement | Version | Notes |
| ----------- | ------- | ----- |
| Python | 3.10+ | Check with `python3 --version` |
| pip | current | Bundled with Python |
| Airtable base | configured | See schema in [specification.md](specification.md) |
| Anthropic API key | — | Required for AI alt text and tags |

Optional (stock photo search):

| Requirement | Notes |
| ----------- | ----- |
| Pexels API key | Free at pexels.com/api |
| Shutterstock client ID + secret | Free dev tier at shutterstock.com/developers |
| Unsplash access key | Free at unsplash.com/developers |

---

## Initial Setup

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd proxima-image-library

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — fill in API keys and IMAGE_FOLDER path
```

**Minimum `.env` for development (TEST_MODE — no Airtable required):**

```bash
ANTHROPIC_API_KEY=sk-ant-...
IMAGE_FOLDER=/path/to/your/images
TEST_MODE=true
```

**Full `.env` for live Airtable:**

```bash
ANTHROPIC_API_KEY=sk-ant-...
AIRTABLE_API_KEY=pat...
AIRTABLE_BASE_ID=app...              # must match pattern app + 14 alphanumeric chars
AIRTABLE_TABLE_NAME=Assets
IMAGE_FOLDER=/path/to/your/images
SUPPORTED_FORMATS=.jpg,.jpeg,.png,.gif,.webp
```

---

## Running the App

**Development (TEST_MODE — safe, no external writes):**

```bash
TEST_MODE=true python3 -m flask --app src.app run --port 5000
```

**Live (writes to Airtable):**

```bash
python3 -m flask --app src.app run --port 5000
```

Open **http://localhost:5000** in your browser.

> If port 5000 is in use on macOS, disable **AirPlay Receiver** in System Settings → General → AirDrop & Handoff.

---

## Running Tests

```bash
pytest
```

Tests live in `tests/` and use `pytest`. No `.env` required — tests instantiate modules directly with `tmp_path` fixtures and do not call any external APIs.

```bash
pytest -v                   # verbose output
pytest tests/test_rename_assets.py   # single file
```

---

## Architecture Overview

```text
src/
├── app.py              Flask routes and server — the entry point for the web UI
├── main.py             CLI orchestrator — scan → generate → upload pipeline
├── ai_generator.py     Claude vision API — alt text (125 chars max) and tags
├── airtable_client.py  Airtable HTTP wrapper — CRUD, batch ops, pagination
├── local_client.py     Drop-in local JSON store — identical interface to airtable_client
├── image_scanner.py    Recursive image discovery via Path.rglob()
├── config.py           Env var validation and Config object
├── rename_assets.py    Batch rename to {prefix}-{slug}.{ext} format
└── stock_client.py     Pexels / Shutterstock / Unsplash search, concurrent

templates/
├── launcher.html       Dashboard — 4 feature cards
├── index.html          Library browser — folder → tag → grid → detail
└── stock_search.html   Stock photo search — upload/paste → phrase chips → results

tests/
└── test_rename_assets.py   pytest — covers slugify, build_plan, ImageScanner
```

### Dual-backend pattern

`AirtableClient` and `LocalClient` share identical method signatures. `TEST_MODE=true` swaps one for the other — no code changes needed to switch. All new data-layer features must be implemented in **both** clients.

```text
TEST_MODE=true  →  LocalClient  →  test_data/local_table.json
TEST_MODE=false →  AirtableClient  →  Airtable API
```

---

## How To: Common Tasks

### Add a Flask route

1. Add the route function to [src/app.py](src/app.py)
2. If it returns HTML, add a template to `templates/`
3. If it's an API endpoint, return `jsonify(...)` with a consistent shape
4. Add a link or card in `templates/launcher.html` if it's a top-level feature

```python
@app.route("/my-feature")
def my_feature():
    return render_template("my_feature.html")

@app.route("/api/my-data", methods=["POST"])
def api_my_data():
    data = request.get_json(force=True)
    # ...
    return jsonify({"result": ...})
```

Security checklist for new routes:
- Never construct file paths from user input without resolving and checking against `IMAGE_FOLDER`
- Use `unquote()` on URL-encoded path parameters before resolving
- Always validate at the boundary — trust nothing from `request`

### Add a new Airtable field

1. Add the field to the Airtable base manually (Airtable UI)
2. Update `create_record()` and `update_record()` in **both** [src/airtable_client.py](src/airtable_client.py) and [src/local_client.py](src/local_client.py)
3. Update the Airtable schema table in [specification.md](specification.md)

### Add a new AI-generated field

1. Add a `generate_<field>()` method to `AltTextGenerator` in [src/ai_generator.py](src/ai_generator.py) following the same pattern as `generate_tags()`
2. Call it in the pipeline in [src/main.py](src/main.py) alongside the existing `generate_alt_text()` / `generate_tags()` calls
3. Pass the result to `create_record()` (which requires the Airtable field to exist — see above)

Keep the model pinned to `claude-sonnet-4-6`. Do not change it without discussion.

### Add a new stock photo API

1. Add a `search_<name>(phrase, limit)` function to [src/stock_client.py](src/stock_client.py) returning `{"results": [...], "error": str|None}`
2. Each result dict must include at minimum: `thumb`, `title`, `link`
3. Add the new searcher to the `searchers` dict in `search_all_libraries()`
4. Add the new tab to the `LIBS` array in `templates/stock_search.html`
5. Document the API in [search-parameter.md](search-parameter.md)

### Modify the launcher

The launcher at `templates/launcher.html` is a 4-card grid. To add a card:

```html
<a class="card" href="/my-feature">
  <div class="card-icon">🔍</div>
  <div class="card-title">My Feature</div>
  <div class="card-desc">Short description shown under the title.</div>
</a>
```

### Rebuild the macOS app

After editing `Start Server.applescript`:

```bash
cd /path/to/proxima-image-library
osacompile -o "Start Server.app" "Start Server.applescript"
cp /tmp/proxima2.icns "Start Server.app/Contents/Resources/applet.icns"
plutil -replace CFBundleName -string "Proxima Photos" "Start Server.app/Contents/Info.plist"
plutil -replace CFBundleDisplayName -string "Proxima Photos" "Start Server.app/Contents/Info.plist"
cp -R "Start Server.app" "/Applications/Proxima Photos.app"
```

---

## Code Conventions

| Convention | Rule |
| ---------- | ---- |
| AI model | Always `claude-sonnet-4-6` — do not change without discussion |
| Data layer | Every new feature uses the dual-backend pattern — implement in both clients |
| Path handling | Always resolve paths and validate against `IMAGE_FOLDER` before serving files |
| API caching | `/api/*` endpoints are cached for 5 minutes — keep responses stateless |
| Status values | Airtable Status field uses hyphens: `pending-review`, `reviewed`, `archived` |
| File naming | New image files follow `{prefix}-{slug}.{ext}` — see [specification.md](specification.md) |
| Tag vocabulary | Tags are drawn from the predefined list in [specification.md](specification.md) — do not invent new tags in code |
| Alt text | Max 125 characters; no "Image of" or "Picture of" prefix |

---

## Environment Variables Reference

| Variable | Required | Default | Description |
| -------- | -------- | ------- | ----------- |
| `ANTHROPIC_API_KEY` | Always | — | Claude API key |
| `AIRTABLE_API_KEY` | Live mode | — | Airtable personal access token |
| `AIRTABLE_BASE_ID` | Live mode | — | Must match `app` + 14 alphanumeric chars |
| `AIRTABLE_TABLE_NAME` | Live mode | `Assets` | Airtable table name |
| `IMAGE_FOLDER` | Always | `./assets` | Absolute path to local image directory |
| `SUPPORTED_FORMATS` | No | `.jpg,.jpeg,.png,.gif,.webp` | Comma-separated extensions |
| `TEST_MODE` | No | `false` | `true` uses local JSON store instead of Airtable |
| `PEXELS_API_KEY` | Stock search | — | Pexels API key |
| `SHUTTERSTOCK_CLIENT_ID` | Stock search | — | Shutterstock app client ID |
| `SHUTTERSTOCK_CLIENT_SECRET` | Stock search | — | Shutterstock app client secret |
| `UNSPLASH_ACCESS_KEY` | Stock search | — | Unsplash access key |

---

## Known Issues and Gotchas

| Issue | Cause | Fix / Workaround |
| ----- | ----- | ---------------- |
| Port 5000 in use | macOS AirPlay Receiver | System Settings → General → AirDrop & Handoff → disable AirPlay Receiver |
| SSL warning on startup | urllib3 v2 / LibreSSL incompatibility | Non-blocking — safe to ignore |
| Airtable record not found | Status value uses underscore | Status must use hyphens: `pending-review` not `pending_review` |
| Stock search tab shows "not configured" | Missing env var | Add the relevant API key(s) to `.env` |
| Thumbnail returns 500 | Image format unreadable by Pillow (e.g. CMYK JPEG) | Convert source image to sRGB before adding to `IMAGE_FOLDER` |
| `build_plan` re-renames already-named files | Slug is derived from the full stem, including the prefix | Re-running rename on already-renamed files is safe but will double-prefix — run rename once per batch |

---

## Reference Documents

| Document | Purpose |
| -------- | ------- |
| [project-scope.md](project-scope.md) | Feature definitions, application parameters, storage requirements |
| [specification.md](specification.md) | Image output targets, naming convention, Airtable schema, AI metadata spec |
| [search-parameter.md](search-parameter.md) | Stock photo API parameters, authentication, attribution requirements |
| [README.md](README.md) | Quick start and end-user reference |
