# Asset Library - AI Image Alt-Text Generator

Automatically generate descriptive alt text for your image assets using Claude's vision capabilities, with seamless Airtable integration for management and review.

## Features

- 🖼️ **Automatic Image Discovery** - Recursively scans folders for all supported image formats
- 🤖 **AI-Powered Alt Text** - Uses Claude's vision to generate accessible, SEO-friendly alt text
- 📊 **Airtable Integration** - Stores images, alt text, tags, and status in Airtable
- 🔄 **Batch Processing** - Process multiple images in one run
- 📋 **Status Tracking** - Track which images are pending, reviewed, or completed
- ✏️ **Easy Updates** - Regenerate alt text for specific images anytime

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Your Environment

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Required configuration:
- **AIRTABLE_API_KEY** - Get from [Airtable Account Settings](https://airtable.com/account)
- **AIRTABLE_BASE_ID** - Found in Airtable URL: `https://airtable.com/{BASE_ID}/...`
- **AIRTABLE_TABLE_NAME** - Name of your table (default: "Assets")
- **ANTHROPIC_API_KEY** - Get from [Anthropic Console](https://console.anthropic.com)
- **IMAGE_FOLDER** - Path to your images (default: `./assets`)

### 3. Prepare Airtable

Create a table in Airtable with these columns:
- **Filename** (Text) - Name of the image file
- **Image** (Attachment) - Image file
- **Alt Text** (Long Text) - Generated or edited alt text
- **Tags** (Text) - Optional tags for categorization
- **Status** (Single select) - Options: pending_review, reviewed, archived

### 4. Add Your Images

Place images in the `./assets` folder (or your configured `IMAGE_FOLDER`):

```
assets/
├── photo1.jpg
├── photo2.png
└── subfolder/
    └── photo3.webp
```

### 5. Run the Sync

```bash
python -m src.main
```

This will:
1. Scan for all new images
2. Generate alt text for each using Claude
3. Create records in Airtable
4. Mark them as "pending_review"

## Rename Files Before Sync (Recommended)

If you want consistent, license-safe naming before ingesting to Airtable, use the built-in renamer.

Default naming format:

```
{prefix}-{index:04d}-{slug}.{ext}
```

Example:

```
proxima-0001-square-katie-web4.webp
```

Dry-run preview (no changes):

```bash
python -m src.rename_assets --prefix proxima
```

Apply renames:

```bash
python -m src.rename_assets --prefix proxima --apply
```

This command also writes a CSV mapping file (`rename_map.csv`) with old and new paths for audit/history.

## Usage

### Sync New Images

```bash
python -m src.main
```

### Regenerate Alt Text for a Specific Image

```python
from src.main import AssetLibrary

library = AssetLibrary()
library.regenerate_alt_text("photo1.jpg", context="Product photography for e-commerce")
```

### View Processing Status

```python
from src.main import AssetLibrary

library = AssetLibrary()
library.list_images_status()
```

## Folder Structure

```
asset-library/
├── src/
│   ├── __init__.py
│   ├── main.py              # Main orchestrator
│   ├── config.py            # Configuration management
│   ├── airtable_client.py   # Airtable API interactions
│   ├── ai_generator.py      # Claude alt-text generation
│   └── image_scanner.py     # Image discovery & processing
├── assets/                  # Your image files
├── tests/                   # Test suite (optional)
├── requirements.txt         # Python dependencies
├── .env                     # Your secret API keys (not in git)
├── .env.example             # Configuration template
└── README.md               # This file
```

## Supported Image Formats

- `.jpg`, `.jpeg`
- `.png`
- `.gif`
- `.webp`

Configure additional formats in `.env` via `SUPPORTED_FORMATS`.

## Alt Text Quality

The generated alt text:
- Is concise and descriptive (max 125 characters by default)
- Follows web accessibility best practices
- Doesn't include "Image of" or "Picture of" prefix
- Is optimized for screen readers
- Can be customized with context

Example context usage:
```python
library.regenerate_alt_text(
    "product.jpg", 
    context="Product photography for online store - men's footwear"
)
```

## Workflow

### Recommended Workflow

1. **Initial Sync** - Run the tool to generate alt text for all images
2. **Review in Airtable** - Check generated alt text, edit if needed
3. **Update Status** - Mark as "reviewed" or "archived" in Airtable
4. **Bulk Edits** - Use Airtable's batch operations for updates
5. **Regenerate** - Use the tool to regenerate alt text when you update images

## Troubleshooting

### "Missing required environment variables"
- Check that `.env` file exists and is properly formatted
- Verify all required API keys are valid
- Never commit `.env` file to version control

### "Image folder not found"
- Ensure the `IMAGE_FOLDER` path in `.env` is correct
- Create the folder if it doesn't exist: `mkdir assets`

### "Airtable API error"
- Verify `AIRTABLE_API_KEY` and `AIRTABLE_BASE_ID` are correct
- Ensure your Airtable table has the required columns
- Check API rate limits

### "Claude API error"
- Verify `ANTHROPIC_API_KEY` is valid
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
