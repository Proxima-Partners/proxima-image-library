# Proxima Image Library

Scans a local image folder, generates alt text via Claude, syncs metadata to Airtable, and provides a web interface for browsing the library.

## Setup

```bash
pip3 install -r requirements.txt
cp .env.example .env   # fill in API keys and IMAGE_FOLDER
```

Required `.env` vars: `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME`, `ANTHROPIC_API_KEY`, `IMAGE_FOLDER`

## Web Interface

Browse, filter, and download images via a local web app:

```bash
python3 -m flask --app src.app run --port 5001
```

Open **http://localhost:5001** in your browser.

**4-step flow:**
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
Output format: `proxima-0001-slug-of-name.jpg`. Writes `rename_map.csv` for audit.

**Sync to Airtable:**
```bash
python3 -u -m src.main
```
Scans `IMAGE_FOLDER`, generates alt text + tags for new images via Claude, creates Airtable records with status `pending-review`.

**Clear all Airtable records:**
```python
from dotenv import load_dotenv; load_dotenv('.env')
from src.airtable_client import AirtableClient
AirtableClient().delete_all_records()
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

- SSL warning on every run is non-blocking (urllib3 v2 / LibreSSL incompatibility)
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` (configurable via `SUPPORTED_FORMATS`)
- Airtable status value must use a dash: `pending-review` not `pending_review`
- Images are served directly from `IMAGE_FOLDER` — Airtable holds metadata only
