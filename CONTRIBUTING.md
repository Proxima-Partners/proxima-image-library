# Contributing to Proxima Image Library

This document is for developers joining the project. The application is an **Anthropic-native stack** — it uses Claude AI models exclusively and is built for the Anthropy platform. If you use an OpenAI-based coding assistant (ChatGPT, Copilot, Cursor), read this document carefully before making any changes. Many default suggestions from OpenAI tools will conflict with this project's architecture.

---

## The Golden Rules

1. **Never change the AI model string.** It is always `claude-sonnet-4-6`. Do not let your coding assistant replace it with any OpenAI model, any other Claude model, or a variable.
2. **Never replace the Anthropic SDK.** All AI calls use `anthropic.Anthropic()`. Do not substitute `openai`, `langchain`, or any other library.
3. **Every data-layer change must be made in both clients.** `LocalClient` and `SharePointListClient` share the same interface. If you add or change a method in one, you must mirror it in the other.
4. **Do not restructure the project.** Framework migrations, ORM introductions, and folder reorganizations are out of scope without explicit approval.
5. **Always read `development.md` and `specification.md` before making changes.** They are the authoritative source for conventions, schema, and architecture decisions.

---

## What Your AI Coding Assistant Will Suggest — And Why To Reject It

OpenAI-based assistants frequently suggest patterns that are correct in general but will break this specific application. Know these before you start.

### AI model substitution

Your assistant will often auto-complete or suggest:

```python
# DO NOT USE
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(model="gpt-4o", ...)

# DO NOT USE
model="claude-3-5-sonnet-20241022"   # wrong model version
model="claude-opus-4-6"              # wrong model for this app
```

The correct pattern, already in the codebase:

```python
# CORRECT
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(model="claude-sonnet-4-6", ...)
```

Do not change the model string without a team discussion. It is pinned intentionally.

### Replacing Flask with FastAPI or async frameworks

This app uses synchronous Flask with SSE streaming via `queue.Queue` and `threading.Thread`. Your assistant may suggest converting routes to `async def` or migrating to FastAPI. Do not do this — the SSE pattern, `session`, and `@login_required` decorator all depend on the synchronous Flask context.

### Adding an ORM or replacing the dual-backend pattern

Your assistant may suggest SQLAlchemy, SQLite, or a single unified data class. The project uses a deliberate dual-backend pattern:

```text
TEST_MODE=true  →  LocalClient          →  test_data/local_table.json
TEST_MODE=false →  SharePointListClient →  SharePoint List (Microsoft Graph API)
```

This allows fully offline local development with no SharePoint access. Do not collapse these into one class or add a database dependency.

### Changing `local_client.py` without considering thread safety

`LocalClient` is called concurrently by Flask (multiple requests at once). The file uses a module-level `_LOCK` and atomic writes. Your assistant may suggest simplifying `_save()` back to a plain `open(..., "w")` write. Do not do this — it will corrupt `local_table.json` under concurrent requests (this has happened and been fixed).

### Relative paths in the MCP server

Your assistant may simplify path expressions in `src/mcp_server.py`. All paths must be anchored to `__file__`:

```python
# CORRECT — works regardless of cwd when Claude Desktop launches the server
load_dotenv(Path(__file__).parent.parent / ".env")
_DEFAULT_PATH = Path(__file__).parent.parent / "test_data" / "local_table.json"

# WRONG — breaks when Claude Desktop sets a different working directory
load_dotenv(".env")
_DEFAULT_PATH = Path("test_data/local_table.json")
```

### Using `request.args` or user input directly in file paths

Never construct a file path directly from user input. Always resolve and validate against `IMAGE_FOLDER`:

```python
# CORRECT
safe = (Path(Config.IMAGE_FOLDER) / rel_path).resolve()
if not str(safe).startswith(str(Path(Config.IMAGE_FOLDER).resolve())):
    abort(400)

# WRONG — path traversal vulnerability
path = Path(request.args.get("path"))
```

### Inventing new status values or tag names

Status values are a closed set using hyphens: `pending-review`, `approved`, `rejected`, `archived`. Tags must come from the predefined vocabulary in `specification.md`. Do not add new values without updating the spec.

---

## Architecture Overview

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

---

## File and Schema Conventions

### Image file naming

```
{prefix}-{slug}.webp          (WebP delivery copy)
{slug}-original.{ext}         (High-Res original)
```

Slugs: lowercase, hyphens only, max 60 characters.

### SharePoint List / LocalClient field names

Use the exact field names from `specification.md`. Field names are case-sensitive and use Title Case with spaces (e.g. `Alt Text`, `High-Res Location`, `Status`). The `_TO_SP` mapping in `SharePointListClient` translates these to Graph API internal names — do not bypass it.

### JSON record shape (`test_data/local_table.json`)

```json
{
  "id": "loc_<hex>",
  "fields": {
    "Filename": "proxima-example.webp",
    "Alt Text": "...",
    "Tags": "tag1, tag2",
    "Status": "approved",
    "Slug": "...",
    "Location": "Category/filename.webp",
    "High-Res Location": "Category/filename-original.jpeg"
  }
}
```

Do not add top-level keys outside `fields`. Do not rename `id`.

---

## Before You Push

Run through this checklist:

- [ ] No `openai`, `langchain`, or non-Anthropic AI library added to `requirements.txt`
- [ ] Model string is still `claude-sonnet-4-6` everywhere
- [ ] Any new data method is implemented in **both** `LocalClient` and `SharePointListClient`
- [ ] Any new Flask route uses `@login_required`
- [ ] No raw string concatenation for file paths — use `pathlib.Path`
- [ ] MCP server paths still anchored to `__file__`
- [ ] `pytest` passes: `source .venv/bin/activate && pytest`
- [ ] App starts cleanly in TEST_MODE: `flask --app src.app run --port 5000 --debug`
- [ ] EDIT_LIST.md updated if a pending item was completed

---

## Environment

**Development (safe — no SharePoint writes):**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in ANTHROPIC_API_KEY, IMAGE_FOLDER, MSAL vars
flask --app src.app run --port 5000 --debug
```

Set `TEST_MODE=true` and `STORAGE_MODE=local` in `.env` for fully local dev.

**Do not commit `.env`.** It is in `.gitignore`. Do not hardcode keys.

Full environment variable reference: [development.md](development.md#environment-variables-reference)

---

## Key Documents

| Document | Read before... |
| -------- | -------------- |
| [development.md](development.md) | Any code change |
| [specification.md](specification.md) | Touching image processing, file naming, or SharePoint fields |
| [EDIT_LIST.md](EDIT_LIST.md) | Starting any feature work — check what is queued and what is applied |
| [PRODUCTION_DEPLOY.md](PRODUCTION_DEPLOY.md) | Any production deployment |
| [project-scope.md](project-scope.md) | Understanding why a feature exists |

---

## Questions

If your coding assistant gives you a suggestion and you are unsure whether it conflicts with this document, check `development.md` first. When in doubt, ask before merging.
