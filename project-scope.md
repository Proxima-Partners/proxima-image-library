# Project: Proxima Image Library

Locates image files based on description. Retrieves the file based on user selection. Transforms images for consistency, identifies the image using Claude AI vision, and pushes the image to SharePoint and CMS.

## Technology Stack

- **Backend:** Python 3 + Flask — serves the web UI and API endpoints
- **AI:** Claude vision API (claude-sonnet-4-6) — generates alt text and tags from image content
- **Metadata store:** SharePoint List — stores filenames, alt text, tags, status, slug, location (WebP path), and high-res location
- **Image storage:** Proxima SharePoint (production); local folder (development/testing)
- **Security:** Microsoft Azure required for SharePoint authentication and access control (live mode)

## Feature Status

| Feature | Description | Status |
| ------- | ----------- | ------ |
| 1 | Search and selection (triggered from Proxima Writing) | Implemented |
| 2 | Catalog external images via upload | Implemented |
| 3 | Stock photo search (Pexels, Shutterstock, Unsplash, Pixabay) | Implemented |
| 4 | Internal image search (local library) | Implemented |
| 5 | Utility / maintenance tools | Implemented |

## Workflow Definition

### Feature 1: Search and Selection Workflow

1. Feature triggered via the Proxima Writing project (external integration — method TBD)
2. App runs the search protocol

### Feature 2: Catalog External Image Workflow

1. User is provided an upload section for multiple entries, allowing browse or drag-and-drop
2. Uploaded files are staged to local disk, then transferred to SharePoint
3. App runs the search protocol for each image

### Feature 3: Image Search Workflow (Stock Photos)

1. User provides search parameters
    - Search criteria are defined per API in `search-parameter.md`
    - Each API (Pexels, Shutterstock, Unsplash, Pixabay) has unique supported parameters
    - UI collects parameters with instruction/help text per field
2. Image is processed via search protocol
3. Completion status returned to user

### Feature 4: Internal Image Search

1. User provides search parameters via UI
2. App searches the existing SharePoint List
3. Results displayed; user selects an image
4. Selected image returned to calling context

### Feature 5: Utility Features

1. **Library maintenance**
    - Compare image files in SharePoint to SharePoint List records
    - Process new or modified files found in SharePoint
    - Offer user option to delete SharePoint List record if the image file is missing
2. **Clean and reindex**
    - Deletes all SharePoint List records
    - Scans the SharePoint image library and processes each image to repopulate the List

## Search Protocol

1. Collect and validate search parameters from user
2. Submit search to external stock photo API (Feature 3) or query SharePoint List (Feature 4)
3. Display image selection UI with results
4. Download the selected image at the highest resolution available
5. Store original high-res image in SharePoint (`/High-Res/`)
6. Transform image to WebP format per specifications in `specification.md`
7. Pass image to Claude AI vision to generate alt text (max 125 chars) and tags
8. Write metadata (filename, alt text, tags, slug, location) to SharePoint List record
9. Store transformed WebP image in SharePoint location defined by the List record
10. Return image parameters to UI and display completion status

## Application Parameters

1. Image files located in Proxima SharePoint storage (local folder used for development/testing via `TEST_MODE=true`)
2. Two parallel storage structures maintained: `High-Res/` and `WebP/`
3. High-Res: highest resolution available from original source
4. WebP: each image converted to `.webp` format, transformed per `specification.md`
5. UI delivered via external hosted HTML (e.g., Webflow or CMS-hosted); local Flask server used for development and testing only
6. All storage must be secured via Microsoft Azure authentication (SharePoint API access via Azure AD)
7. Follow security best practices: no credentials in code, path traversal protection, input validation on all API boundaries

## Supporting Reference Files

| File | Purpose |
| ---- | ------- |
| `search-parameter.md` | Defines search parameters accepted by each stock photo API |
| `specification.md` | Defines image transformation targets (dimensions, format, quality) |
