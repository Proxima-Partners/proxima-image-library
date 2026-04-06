# Project: Proxima Image Library

Locates image files based on description. Retrieves the file based on user selection. Transforms images for consistency, identifies the image using Claude AI vision, and pushes the image to SharePoint and CMS.

## Technology Stack

- **Backend:** Python 3 + Flask — serves the web UI and API endpoints
- **AI:** Claude vision API (`claude-sonnet-4-6`) — generates alt text and tags from image content
- **Metadata store:** SharePoint List — stores filename, alt text, tags, status, slug, location (WebP path)
- **Image storage:** SharePoint document library (production); local `IMAGE_FOLDER` (development via `STORAGE_MODE=local`)
- **Auth:** MSAL (Microsoft Authentication Library) — all Flask routes protected; MSAL session cookie with token-claim expiry enforcement
- **Integration:** MCP server (`src/mcp_server.py`) exposes tools to Claude Desktop for writing workflow

## Feature Status

| Feature | Description | Status |
| ------- | ----------- | ------ |
| 1 | Search and selection (triggered from Proxima Writing via MCP) | Implemented |
| 2 | Catalog external images via upload | Implemented |
| 3 | Stock photo search (Pexels, Shutterstock, Unsplash, Pixabay) with rich metadata modals | Implemented |
| 4 | Internal image search (local library) | Implemented |
| 5 | Utility / maintenance tools | Implemented |
| 6 | Image review workflow (`/review` page, status badges, approve/reject/archive) | Implemented |
| 7 | MCP `catalog_image_from_file` tool (base64 upload from Claude Desktop) | Implemented |

## Workflow Definition

### Feature 1: Search and Selection Workflow

1. Triggered via the Proxima Writing Claude Desktop project — writing skill output (Blog or Article) auto-calls `search_image_library` MCP tool with Photo Suggestion phrases
2. MCP tool returns ranked results with inline thumbnail images
3. User selects from thumbnails; if no match, `search_stock_photos` is called
4. Selected stock image is downloaded and catalogued via the full processing pipeline; new records land in `pending-review`

### Feature 2: Catalog External Image Workflow

1. User is provided an upload section for multiple entries, allowing browse or drag-and-drop
2. Uploaded files are staged to local disk, then transferred to SharePoint
3. App runs the processing pipeline for each image (resize → WebP → Claude vision → metadata record)
4. New records created with `status=pending-review` for review queue sign-off

### Feature 3: Image Search Workflow (Stock Photos)

1. User provides search parameters via the stock search UI
    - Each API (Pexels, Shutterstock, Unsplash, Pixabay) has unique supported parameters per `search-parameter.md`
    - Results include full metadata: dimensions, color, tags, credits, editorial flag
2. User selects an image; rich metadata modal shows before download confirmation
3. Download proxied via `/api/download-image` (CDN allowlist, Unsplash attribution ping)
4. "Add to Library" streams catalog progress via SSE; image processed with stock source context passed to Claude for richer metadata
5. New record created with `status=pending-review`

### Feature 4: Internal Image Search

1. User arrives at the search-first home screen — hero view with large search bar, category tiles, and recently added strip
2. User enters a keyword or clicks a category tile to enter browse view
3. App searches the SharePoint List (or local JSON in TEST_MODE) and renders a filtered image grid
4. User selects an image; detail panel shows alt text, tags, and download option

### Feature 5: Utility Features

1. **Library maintenance**
    - Dedicated `/maintenance` console for sync, orphan detection, duplicate resolution, retag, status reset, broken thumbnail handling, and CSV export
    - Governance operations: health snapshot, integrity scorecard, drift queue, category normalization, checkpoints, scheduled jobs, audit trail, and approvals
    - Destructive operations enforce guardrails (`expected_count`, max batch, optional approval token, optional checkpoint)
2. **Clean and reindex**
    - Controlled maintenance paths with confirmation and approval flow
    - Bulk operations support both local TEST mode and SharePoint live mode

### Feature 6: Image Review Workflow

1. Newly catalogued images (via upload, stock download, or MCP tool) are created with `status=pending-review`
2. Reviewer navigates to `/review` — queue shows all pending images with thumbnail, editable alt text, and tag chips
3. Reviewer can approve, reject, or archive each image individually or use Approve All
4. Home page nav shows an amber badge with the live pending count; badge refreshes on return to page
5. Status changes are immediately reflected (cache invalidated on each PATCH)

### Feature 7: MCP `catalog_image_from_file` Tool

1. User drops an image file directly into the Claude Desktop writing session
2. Claude calls `catalog_image_from_file` with base64 image data, filename, and category
3. MCP tool decodes the image, runs the full processing pipeline (resize → WebP → Claude vision → metadata record)
4. Record created with `status=pending-review`; tool returns slug, alt text, and tags to Claude

## Search Protocol

1. Collect and validate search parameters from user
2. Submit search to external stock photo API (Feature 3) or query SharePoint List (Feature 4)
3. Display image selection UI with results and inline thumbnails
4. Download the selected image at the highest resolution available
5. Store original high-res image in `High-Res/` (source-based subfolder)
6. Transform image to WebP format per `specification.md`
7. Pass image to Claude vision to generate alt text (max 125 chars) and tags; provide stock source metadata as context
8. Write metadata (filename, alt text, tags, slug, location, status=pending-review) to SharePoint List record
9. Store transformed WebP in SharePoint at the location defined by the List record
10. Return image parameters to UI and display completion status

## Application Parameters

1. Image files in SharePoint (production) or `IMAGE_FOLDER` local path (development, `STORAGE_MODE=local`)
2. Two parallel storage structures: `High-Res/` and `WebP/`
3. High-Res: highest resolution from original source; uses source-based subfolders (`ShutterStock`, `AdobeStock`, `Unsplash`, `Pexels`, `Pixabay`, `Internal`)
4. WebP: converted to `.webp`, transformed per `specification.md`; organized by content category
5. UI delivered via Flask-rendered templates; shares auth session with the API
6. All storage secured via MSAL authentication (Microsoft Azure AD)
7. Security: no credentials in code, path traversal protection, input validation at all API boundaries
8. All new records created with `status=pending-review`; must pass review queue before considered approved
9. Maintenance endpoints are allowlist-gated via `MAINTENANCE_ADMIN_USERS` (except local auth bypass in TEST mode)
10. Local MSAL testing should use `localhost` consistently; mixing `localhost` and `127.0.0.1` can break auth state continuity
11. TEST_MODE includes a deterministic auth-session expiry helper endpoint: `POST /auth/test-expire-session`

## Supporting Reference Files

| File | Purpose |
| ---- | ------- |
| `search-parameter.md` | Defines search parameters accepted by each stock photo API |
| `specification.md` | Defines image transformation targets (dimensions, format, quality) |
| `EDIT_LIST.md` | Applied changes and future development queue |
| `PRODUCTION_DEPLOY.md` | Azure App Service deployment checklist |

---

## Developer Onboarding

This application is an **Anthropic-native stack** — it uses Claude AI models exclusively and is built for the Anthropy platform. If you use an OpenAI-based coding assistant (ChatGPT, Copilot, Cursor), read this section carefully before making any changes. Many default suggestions from OpenAI tools will conflict with this project's architecture.

### The Golden Rules

1. **Never change the AI model string.** It is always `claude-sonnet-4-6`. Do not let your coding assistant replace it with any OpenAI model, any other Claude model, or a variable.
2. **Never replace the Anthropic SDK.** All AI calls use `anthropic.Anthropic()`. Do not substitute `openai`, `langchain`, or any other library.
3. **Every data-layer change must be made in both clients.** `LocalClient` and `SharePointListClient` share the same interface. If you add or change a method in one, you must mirror it in the other.
4. **Do not restructure the project.** Framework migrations, ORM introductions, and folder reorganizations are out of scope without explicit approval.
5. **Always read `development.md` and `specification.md` before making changes.** They are the authoritative source for conventions, schema, and architecture decisions.

### What Your AI Coding Assistant Will Suggest — And Why To Reject It

OpenAI-based assistants frequently suggest patterns that are correct in general but will break this specific application.

**AI model substitution** — Your assistant will often auto-complete or suggest:

```python
# DO NOT USE
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(model="gpt-4o", ...)

# DO NOT USE — wrong model version or wrong model for this app
model="claude-3-5-sonnet-20241022"
model="claude-opus-4-6"
```

The correct pattern already in the codebase:

```python
# CORRECT
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(model="claude-sonnet-4-6", ...)
```

**Replacing Flask with FastAPI or async frameworks** — This app uses synchronous Flask with SSE streaming via `queue.Queue` and `threading.Thread`. Do not convert routes to `async def` or migrate to FastAPI — the SSE pattern, `session`, and `@login_required` all depend on the synchronous Flask context.

**Adding an ORM or replacing the dual-backend pattern** — Your assistant may suggest SQLAlchemy, SQLite, or a single unified data class. The dual-backend pattern exists deliberately:

```text
TEST_MODE=true  →  LocalClient          →  test_data/local_table.json
TEST_MODE=false →  SharePointListClient →  SharePoint List (Microsoft Graph API)
```

Do not collapse these into one class or add a database dependency.

**Simplifying `local_client.py` writes** — `LocalClient` uses a module-level `_LOCK` and atomic writes (`.tmp` + rename). Do not simplify `_save()` back to a plain `open(..., "w")` — it will corrupt `local_table.json` under concurrent requests. This has already happened and been fixed.

**Relative paths in the MCP server** — All paths in `src/mcp_server.py` must be anchored to `__file__`:

```python
# CORRECT — works regardless of cwd when Claude Desktop launches the server
load_dotenv(Path(__file__).parent.parent / ".env")

# WRONG — breaks when Claude Desktop sets a different working directory
load_dotenv(".env")
```

**User input directly in file paths** — Never construct a file path from user input without validating against `IMAGE_FOLDER`:

```python
# CORRECT
safe = (Path(Config.IMAGE_FOLDER) / rel_path).resolve()
if not str(safe).startswith(str(Path(Config.IMAGE_FOLDER).resolve())):
    abort(400)

# WRONG — path traversal vulnerability
path = Path(request.args.get("path"))
```

**Inventing new status values or tag names** — Status values are a closed set using hyphens: `pending-review`, `approved`, `rejected`, `archived`. Tags must come from the predefined vocabulary in `specification.md`.

### Architecture Overview

```text
Browser → Flask (src/app.py)
              ├── TEST_MODE=true  → LocalClient (local JSON)
              └── TEST_MODE=false → SharePointListClient (Graph API)

Claude Desktop → MCP Server (src/mcp_server.py)
              └── same LocalClient / SharePointListClient switch

Image pipeline (src/image_processor.py)
    input file → Pillow resize → WebP → ai_generator.py (Claude) → create_record()
```

All Flask routes are protected by `@login_required` (MSAL / Azure AD). The `/health` endpoint is intentionally unprotected for Azure App Service health checks.
Session expiry is enforced from the MSAL `exp` claim. In TEST_MODE only, `POST /auth/test-expire-session` can be used to force expiry during manual validation.

### File and Schema Conventions

Image file naming:

```text
{prefix}-{slug}.webp          (WebP delivery copy)
{slug}-original.{ext}         (High-Res original)
```

Slugs: lowercase, hyphens only, max 60 characters. Field names use Title Case with spaces (`Alt Text`, `High-Res Location`, `Status`). Do not bypass the `_TO_SP` mapping in `SharePointListClient`. Do not add top-level keys outside `fields` in `local_table.json`. Do not rename `id`.

### Before You Push

- [ ] No `openai`, `langchain`, or non-Anthropic AI library added to `requirements.txt`
- [ ] Model string is still `claude-sonnet-4-6` everywhere
- [ ] Any new data method implemented in **both** `LocalClient` and `SharePointListClient`
- [ ] Any new Flask route uses `@login_required`
- [ ] No raw string concatenation for file paths — use `pathlib.Path`
- [ ] MCP server paths still anchored to `__file__`
- [ ] `pytest` passes: `source .venv/bin/activate && pytest`
- [ ] App starts cleanly in TEST_MODE: `flask --app src.app run --port 5000 --debug`
- [ ] EDIT_LIST.md updated if a pending item was completed
