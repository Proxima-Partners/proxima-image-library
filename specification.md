# Image Specification

Defines image transformation targets, storage structure, naming conventions, and metadata requirements for the Proxima Image Library. All values here are the authoritative source for implementation — any hardcoded values in the codebase should match these.

## Storage Structure

Every processed image preserves its original, produces a standard web copy, conditionally produces a hero copy, and writes an additive metadata sidecar.

```text
Images/
├── High-Res/
│   ├── ShutterStock/
│   ├── AdobeStock/
│   ├── Unsplash/
│   ├── Pexels/
│   ├── Pixabay/
│   └── Internal/
├── Hero/
│   └── <category>/{slug}.webp
├── Hero-PNG/
│   └── <category>/{slug}.png
├── PNG/
│   └── <category>/{slug}.png
├── WebP/
    ├── Headshots/
    ├── Community/
    ├── Locations/
    ├── Situations/
    ├── Graphics/
│   └── Banners/
└── Metadata/
    └── {slug}.json
```

**High-Res** preserves the original pixel data exactly — no resize, no re-encode. The source format is retained (JPEG, PNG, etc.). Files are stored under source folders (for example, `High-Res/Unsplash/...` or `High-Res/Internal/...`).

**Hero** contains a 2560px-wide WebP only when the EXIF-corrected original is at least 2560px wide. **WebP** remains the standard/legacy delivery location. It contains a 1600px-wide WebP when possible, or a same-width WebP compatibility copy for smaller originals; no output is ever upscaled. **PNG** and **Hero-PNG** hold lossless PNG twins of the standard and hero WebP files, rendered from the same resized pixels (same width and height). They exist for consumers that need PNG; the WebP files stay the delivery default. Images cataloged before PNG support are brought up to date with `scripts/run_png_backfill.py`; until then the download link converts the stored WebP on the fly. **Metadata** stores source facts, derivative details, rights/provenance, quality tier, and normalized focal point without requiring SharePoint List schema changes.

### Category definitions

| Folder | Contents |
| ------ | -------- |
| `Headshots/` | Staff and individual portrait photos |
| `Community/` | People in community contexts — conversations, groups, events, service |
| `Locations/` | SF landmarks, urban scenes, architecture, landscapes |
| `Situations/` | Conceptual/thematic photos — homelessness, isolation, prayer, hardship |
| `Graphics/` | Logos, icons, illustrations, vectors, diagrams |
| `Banners/` | Banner and background images for email/web |

### High-Res source folders

| Folder | Meaning |
| ------ | ------- |
| `ShutterStock/` | Shutterstock source images |
| `AdobeStock/` | Adobe Stock source images |
| `Unsplash/` | Unsplash source images |
| `Pexels/` | Pexels source images |
| `Pixabay/` | Pixabay source images |
| `Internal/` | Uploaded or manually provided internal images |

### Path resolution

The `Location` field stores the category-relative WebP path (e.g. `Headshots/proxima-mike7.webp`). The app constructs full SharePoint paths as:

- **Display/serve:** `Images/WebP/{Location}`
- **Hero delivery:** `Images/Hero/{Location}` when the sidecar has a hero entry
- **PNG twins:** `Images/PNG/{Location as .png}` and `Images/Hero-PNG/{Location as .png}` when the sidecar has `standard.png` / `hero.png`
- **Original download:** `Images/High-Res/{High-Res Location}`
- **Additive metadata:** `Images/Metadata/{Slug}.json`

The `SHAREPOINT_IMAGE_FOLDER` env var sets the root (default: `Images`).

---

## WebP Output Specification

| Parameter | Value | Notes |
| --------- | ----- | ----- |
| Format | `.webp` | Always, regardless of input format |
| Hero width | 2560 px | Generate only when original display width is at least 2560px |
| Standard width | 1600 px | Existing WebP location; never upscale smaller sources |
| Resize mode | Exact target width | Maintain aspect ratio (no crop, no distortion) |
| Quality | 82 | Used for both approved WebP tiers |
| Color space | sRGB | Convert on save if source is a different profile |
| Orientation | EXIF-corrected | Dimensions and pixels use intended display orientation |
| Transparency | Preserved | PNG/WebP alpha retained; JPEG has no alpha to preserve |
| Progressive / lossless | No | Standard lossy WebP |

### Size reference

| Usage context | Typical max dimension | Notes |
| ------------- | --------------------- | ----- |
| Webflow hero image | 1920 × 1080 px | Full-bleed background |
| Article / blog photo | 1280 × 960 px | Inline content image |
| Card / thumbnail | 800 × 600 px | Grid or card component |
| Headshot / portrait | 600 × 800 px | People images |

Websites should prefer the 2560px derivative for eligible full-width heroes and use `focalPoint` for intentional responsive crops.

### Quality classification

| Original display width | Tier | Hero recommendation |
| ---------------------- | ---- | ------------------- |
| 2560px or wider | `hero-ready` | Preferred |
| 1600–2559px | `standard-only` | Acceptable, not Retina-ready for full-width heroes |
| Under 1600px | `low-resolution` | Do not recommend for hero use |

---

## Thumbnail Specification (Browser UI only)

Thumbnails are generated on-the-fly by the Flask app for display in the internal browser. They are **not stored to disk**.

| Parameter | Value |
| --------- | ----- |
| Max dimension | 240 × 240 px |
| Format | JPEG |
| Quality | 85 |
| Color space | RGB (alpha dropped) |
| Implemented in | [src/app.py](src/app.py) — `_serve_image()` |

---

## File Naming Convention

All asset files follow the pattern defined in [src/rename_assets.py](src/rename_assets.py):

```text
{prefix}-{index:04d}-{slug}.{ext}
```

| Component | Description | Example |
| --------- | ----------- | ------- |
| `prefix` | Project identifier | `proxima` |
| `index` | Zero-padded 4-digit sequence number | `0042` |
| `slug` | Lowercase, hyphen-separated words from alt text | `volunteer-serving-meal` |
| `ext` | File extension | `.webp` or `.jpg` |

**Examples:**

```text
proxima-0001-two-volunteers-kitchen-service.webp
proxima-0042-golden-gate-bridge-sunset-landscape.webp
proxima-0103-youth-group-outdoor-celebration.webp
```

**Slug rules:**

- Lowercase only
- Alphanumeric characters and hyphens only (no spaces, underscores, or special characters)
- Multiple hyphens collapsed to one
- Maximum 60 characters

---

## Input Format Support

| Format | Extension(s) | Notes |
| ------ | ------------ | ----- |
| JPEG | `.jpg`, `.jpeg` | Most common source format |
| PNG | `.png` | Preserves transparency in WebP output |
| WebP | `.webp` | Re-encoded to spec if quality or size differs |
| GIF | `.gif` | Static frame only; animation not preserved |

Controlled by the `SUPPORTED_FORMATS` environment variable (default: `.jpg,.jpeg,.png,.gif,.webp`).

---

## AI Metadata Specification

Generated by Claude vision (`claude-sonnet-4-6`) in [src/ai_generator.py](src/ai_generator.py).

### Alt Text

| Parameter | Value |
| --------- | ----- |
| Max length | 125 characters |
| Style | Descriptive, no "Image of" or "Picture of" prefix |
| Purpose | Screen reader accessibility (WCAG 2.1 AA) |
| Model | `claude-sonnet-4-6` |
| Max tokens | 150 |

### Tags

| Parameter | Value |
| --------- | ----- |
| Count | 2–5 tags per image |
| Source | Predefined vocabulary only (no invented tags) |
| Format | Comma-separated string |
| Max tokens | 80 |

**Predefined tag vocabulary:**

| Category | Tags |
| -------- | ---- |
| People | `people`, `headshot`, `group`, `individual`, `staff`, `volunteer`, `family`, `youth`, `children`, `elderly`, `unhoused`, `neighbor`, `community` |
| Location — SF | `city`, `san-francisco`, `bay-area`, `golden-gate`, `mission-district` |
| Location — type | `landscape`, `architecture`, `street`, `cafe`, `office`, `church`, `indoor`, `outdoor`, `park`, `beach`, `mountains`, `waterfront`, `urban`, `suburban`, `rural`, `forest`, `plaza`, `rooftop`, `bridge`, `neighborhood` |
| Emotion / theme | `hope`, `connection`, `service`, `prayer`, `celebration`, `hardship`, `joy`, `loneliness`, `generosity` |
| Content type | `icon`, `logo`, `illustration`, `graphic`, `vector`, `document`, `map`, `badge`, `partner` |
| Framing | `portrait`, `thumbnail`, `banner`, `background`, `photo` |

---

## Library Record Fields

| Field | Type | Description |
| ----- | ---- | ----------- |
| `Filename` | Text | Original filename with extension |
| `Alt Text` | Text | AI-generated alt text (max 125 chars) |
| `Tags` | Text | Comma-separated tag string |
| `Status` | Select | `pending-review` → `approved` / `rejected` / `archived` |
| `Slug` | Text | URL-safe slug derived from alt text |
| `Location` | Text | WebP path relative to `Images/WebP/` (e.g. `Headshots/proxima-mike7.webp`) |
| `High-Res Location` | Text | Original path relative to `Images/High-Res/` (e.g. `Unsplash/proxima-mike7-original.jpg`) |
| `Source` | Text | Canonical source folder name (`ShutterStock`, `AdobeStock`, `Unsplash`, `Pexels`, `Pixabay`, `Internal`) |
| `Image Hash` | Text | 16-char hex dHash of the WebP pixel content; used by the Duplicate Detector to catch re-ingested duplicate photos even when AI-generated alt text/slug differ |

The legacy fields above remain authoritative for existing consumers. `Metadata/{Slug}.json` adds `original`, `hero`, `standard`, original `width`/`height`/format/file size, `qualityTier`, `focalPoint`, provider/source, attribution, license, source URL, and provider asset ID. Focal coordinates default to `{x: 0.5, y: 0.5}` and each coordinate is normalized from 0 to 1. `standard.png` and `hero.png` describe the PNG twins (`location`, `width`, `height`, `fileSize`, `format`).

### Rights metadata

The sidecar's top-level `rights` object holds the per-image record that `Proxima-Brand-System/04-Photography/RIGHTS.md` requires. It is a sibling of `original` (so hero backfill never erases it), every field is optional, and old sidecars without it keep working. `schemaVersion` stays `1`.

| Field | Values |
| ----- | ------ |
| `assetId` | Internal stable ID (defaults to the slug) |
| `source` | `ShutterStock`, `AdobeStock`, `Unsplash`, `Pexels`, `Pixabay`, `Internal` |
| `providerAssetId`, `contributor`, `licenseReference`, `licensee`, `releaseLocation` | Free text |
| `licenseType` | `standard`, `extended`, `editorial`, `free`, `internal`, `unknown` |
| `licensedOn` | `YYYY-MM-DD` |
| `modelRelease`, `propertyRelease` | `released`, `not-required`, `not-released`, `unknown` |
| `approvedChannels` | Any of `web`, `print`, `social`, `fundraising`, `advertising` |
| `expiration` | `YYYY-MM-DD`, `perpetual`, `unknown` |
| `restrictions`, `approvedCrops` | Lists of text |
| `statements` | Append-only `[{by, on, text}]` — what someone said, not proof |
| `verification` | `{status: unverified\|verified, verifiedBy, verifiedOn, evidence}` |

Rules:

- Never invent license data. Blank or `unknown` means not known.
- Writes are read-modify-write. A blank value never erases a stored one, and a different non-empty value only replaces a stored one with `force`.
- `verification.status: verified` is rejected unless `evidence`, `verifiedBy` and `verifiedOn` are all present.
- `original.license` is kept as a one-line summary derived from `rights` for legacy readers.
- **Status** per image: `verified` (verification recorded), `unverified` (all required fields known, not yet verified), `incomplete` (required fields missing), `none` (no rights record). Required fields: licensed stock needs provider asset ID, contributor, license type, license reference, licensed-on date, model release, channels and expiration; free stock needs contributor and license type; internal needs license type, model release and channels.
- **Hold:** `AdobeStock` and `ShutterStock` images are not cataloged (MCP catalog endpoints return `409 {held, missing}`; sync-highres holds them) until `licenseType` and `licenseReference` are present, unless `allow_missing_rights` is set explicitly. Adobe Stock URLs are never added to the download allowlist; catalog licensed files from the downloaded file instead.

API (`X-MCP-Secret`, rate-limited; responses never include secret-bearing delivery URLs):

- `GET /api/mcp/rights?slug=` → `{slug, source, filename, rights, missing, status}`
- `GET /api/mcp/rights?slugs=a,b,…` (≤50) → `{statuses: {slug: status}}`
- `POST /api/mcp/rights` `{slug, rights, force?}` → the GET shape plus `conflicts`
- `POST /api/mcp/catalog-stock` / `catalog-from-file` accept `rights` and `allow_missing_rights`; `catalog-from-file` also accepts `source`.

Scripts: `scripts/record_rights.py` (JSON/CSV import, dry-run by default) and `scripts/export_rights_md.py` (prints RIGHTS.md tables from the API).

---

## Processing Pipeline Reference

```text
Source image (any supported format)
        │
        ├──► High-Res/  ← Copy original, no transformation
        │
        ├──► Hero/      ← If width ≥2560, resize to 2560px wide, WebP q82
        ├──► Hero-PNG/  ← Same hero pixels as lossless PNG
        ├──► WebP/      ← Resize to ≤1600px wide, WebP q82, never upscale
        ├──► PNG/       ← Same standard pixels as lossless PNG
        ├──► Metadata/  ← Original/derivative/rights/focal JSON sidecar
        │
        └──► Legacy metadata store (SharePoint List / local JSON)
                 ← Claude generates alt text + tags
                           Slug derived from alt text
                           Record written with filename, location, status=pending-review
```

This pipeline is implemented in the current codebase for upload and stock-catalog flows.

---

## Auth and Session Notes

- Runtime auth is handled in Flask via MSAL session cookies and `@login_required` route protection.
- Session expiry is enforced from token claims (`exp`) during authenticated requests.
- TEST_MODE-only manual helper endpoint: `POST /auth/test-expire-session`
    - Purpose: deterministic local validation of expired-session behavior
    - Availability: only when `TEST_MODE=true`
    - Method: POST only
