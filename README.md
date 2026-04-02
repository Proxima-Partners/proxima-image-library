# Proxima Image Library

Scans a local image folder, generates alt text and tags via Claude, syncs metadata to Airtable, and provides a web interface for browsing the library.

## Quick Start (macOS)

Open **Proxima Photos** from `/Applications` — it starts the server, prompts to confirm, and opens the launcher in your browser automatically.

Alternatively, start from the terminal:

```bash
pip3 install -r requirements.txt
cp .env.example .env   # fill in API keys and IMAGE_FOLDER

# Start in test mode (no Airtable required)
TEST_MODE=true python3 -m flask --app src.app run --port 5000

# Start with live Airtable
python3 -m flask --app src.app run --port 5000
```

Open **http://localhost:5000** in your browser.

Required `.env` vars: `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME`, `ANTHROPIC_API_KEY`, `IMAGE_FOLDER`

## Web Launcher

The launcher at **http://localhost:5000** provides four actions:

| Card | Description |
|------|-------------|
| **Browse Library** | Filter by folder + tags, browse thumbnail grid, view image detail with download |
| **Scan — Test Mode** | Scan images and generate alt text/tags locally (no Airtable writes) |
| **Scan — Airtable** | Full sync: scan + generate + write records to Airtable |
| **Clean Data** | Delete all Airtable records (prompts for confirmation) |

A **Stop Server** button in the footer shuts down the Flask process cleanly.

### Browser — 4-step flow
1. **Folders** — select one or more asset folders
2. **Tags** — filter by tags scoped to the selected folders
3. **Grid** — thumbnail grid of matching images
4. **Detail** — filename, location, alt text, image size (px + file size), tags, and a Download Original button

## Sync Pipeline

**Rename images** (run once before first sync):
```bash
python3 -m src.rename_assets --prefix proxima          # dry-run preview
python3 -m src.rename_assets --prefix proxima --apply  # apply renames
```
Output format: `proxima-slug-of-name.jpg`. Writes `rename_map.csv` for audit.

**Sync to Airtable:**
```bash
python3 -u -m src.main
```
Scans `IMAGE_FOLDER`, generates alt text + tags for new images via Claude, creates Airtable records with status `pending-review`.

**Clear all Airtable records (Python):**
```python
from dotenv import load_dotenv; load_dotenv('.env')
from src.airtable_client import AirtableClient
AirtableClient().delete_all_records()
```

## Test Mode

Set `TEST_MODE=true` to use a local JSON store (`test_data/local_table.json`) instead of Airtable. Safe for development — no API calls to Airtable.

## macOS App

`Start Server.applescript` and `Stop Server.applescript` in the project root compile to `.app` bundles. The prebuilt **Proxima Photos.app** is installed at `/Applications/Proxima Photos.app`.

To recompile and reinstall after editing the AppleScript:
```bash
cd /path/to/proxima-image-library
osacompile -o "Start Server.app" "Start Server.applescript"
cp /tmp/proxima2.icns "Start Server.app/Contents/Resources/applet.icns"
plutil -replace CFBundleName -string "Proxima Photos" "Start Server.app/Contents/Info.plist"
plutil -replace CFBundleDisplayName -string "Proxima Photos" "Start Server.app/Contents/Info.plist"
cp -R "Start Server.app" "/Applications/Proxima Photos.app"
```

## Airtable Table Schema

| Field | Type |
|-------|------|
| Filename | Text |
| Alt Text | Long Text |
| Tags | Text (comma-separated) |
| Status | Single select (`pending-review`, `reviewed`, `archived`) |
| Slug | Text |
| Location | Text (relative path within IMAGE_FOLDER) |

## Notes

- If port 5000 is in use on macOS, disable **AirPlay Receiver** in System Settings → General → AirDrop & Handoff
- SSL warning on every run is non-blocking (urllib3 v2 / LibreSSL incompatibility)
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` (configurable via `SUPPORTED_FORMATS`)
- Airtable status value must use a dash: `pending-review` not `pending_review`
- Images are served directly from `IMAGE_FOLDER` — Airtable holds metadata only
