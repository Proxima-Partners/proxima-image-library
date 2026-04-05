# Project: Proxima Image Library

Locates image files based on description. Retrieves the file based on user selection. Transforms images for consistency, identifies the image using Claude AI vision, and pushes the image to SharePoint and CMS.

## Technology Stack

- **Backend:** Python 3 + Flask — serves the web UI and API endpoints
- **AI:** Claude vision API (`claude-sonnet-4-6`) — generates alt text and tags from image content
- **Metadata store:** SharePoint List — stores filename, alt text, tags, status, slug, location (WebP path)
- **Image storage:** SharePoint document library (production); local `IMAGE_FOLDER` (development via `STORAGE_MODE=local`)
- **Auth:** MSAL (Microsoft Authentication Library) — all Flask routes protected; MSAL session cookie
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
    - Compare image files in SharePoint to SharePoint List records
    - Process new or modified files found in SharePoint
    - Offer user option to delete record if image file is missing
2. **Clean and reindex**
    - Deletes all SharePoint List records
    - Scans the image library and processes each image to repopulate

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
5. Store original high-res image in `High-Res/` (source-based subfolder — see M8 in EDIT_LIST)
6. Transform image to WebP format per `specification.md`
7. Pass image to Claude vision to generate alt text (max 125 chars) and tags; provide stock source metadata as context
8. Write metadata (filename, alt text, tags, slug, location, status=pending-review) to SharePoint List record
9. Store transformed WebP in SharePoint at the location defined by the List record
10. Return image parameters to UI and display completion status

## Application Parameters

1. Image files in SharePoint (production) or `IMAGE_FOLDER` local path (development, `STORAGE_MODE=local`)
2. Two parallel storage structures: `High-Res/` and `WebP/`
3. High-Res: highest resolution from original source; future structure uses source-based subfolders (ShutterStock, AdobeStock, Pexels, etc.)
4. WebP: converted to `.webp`, transformed per `specification.md`; organized by content category
5. UI delivered via Flask-rendered templates; shares auth session with the API
6. All storage secured via MSAL authentication (Microsoft Azure AD)
7. Security: no credentials in code, path traversal protection, input validation at all API boundaries
8. All new records created with `status=pending-review`; must pass review queue before considered approved

## Supporting Reference Files

| File | Purpose |
| ---- | ------- |
| `search-parameter.md` | Defines search parameters accepted by each stock photo API |
| `specification.md` | Defines image transformation targets (dimensions, format, quality) |
| `EDIT_LIST.md` | Applied changes and future development queue |
| `PRODUCTION_DEPLOY.md` | Azure App Service deployment checklist |
| `CONTRIBUTING.md` | Onboarding guide for new developers — critical conventions and patterns |
