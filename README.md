# Proxima Image Library

Scans a local image folder, generates alt text via Claude, and syncs metadata to Airtable.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in API keys and IMAGE_FOLDER
```

Required `.env` vars: `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME`, `ANTHROPIC_API_KEY`, `IMAGE_FOLDER`

## Commands

**Rename images** (run once before first sync):
```bash
python -m src.rename_assets --prefix proxima          # dry-run preview
python -m src.rename_assets --prefix proxima --apply  # apply renames
```
Output format: `proxima-0001-slug-of-name.jpg`. Writes `rename_map.csv` for audit.

**Sync to Airtable:**
```bash
python -m src.main
```
Scans `IMAGE_FOLDER`, generates alt text for new images, creates Airtable records with status `pending-review`.

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
| Tags | Text |
| Status | Single select (`pending-review`, `reviewed`, `archived`) |

## Notes

- SSL warning on every run is non-blocking (urllib3 v2 / LibreSSL incompatibility)
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` (configurable via `SUPPORTED_FORMATS`)
- Ensure your Claude account has API credits
- Check for image format compatibility

## Development

### Run Tests (Coming Soon)

```bash
pytest tests/
```

### Contributing

Contributions welcome! Please ensure:
- Code follows PEP 8 style guidelines
- New features include tests
- Documentation is updated

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:
- Check the [Documentation](./README.md)
- Review [Airtable Help](https://support.airtable.com)
- Check [Anthropic API Docs](https://docs.anthropic.com)
