# Edit List

Pending changes — rebuild only on approval.

---

## Pending

### 5. Hybrid metadata for stock photo downloads

- When a stock image is downloaded via the app, pre-populate title, alt text, and tags from the source API metadata before passing to Claude
- Pass the pre-populated metadata as context to Claude with instructions to reconcile against the tag library rather than generate from scratch
- Reduces Claude API cost and processing time while maintaining tag vocabulary consistency
- Per-source mapping needed: Pexels (`alt`, `photographer`), Unsplash (`alt_description`, `tags[].title`), Pixabay (`tags` string split), Shutterstock (`description`, `keywords`)
- Applies to: `src/app.py` upload/process pipeline, `src/stock_client.py`

### 4. Increase stock search results per library

- Current default is 8 results per library per phrase, capped at 12
- Raise default to 12, cap to 20
- Change `limit: 8` in `templates/stock_search.html` and `min(..., 12)` to `min(..., 20)` in `src/app.py`

### 3. Increase Shutterstock modal thumbnail size

- The image thumbnail in the SS quota modal (`#ss-preview`) is small (90×68px)
- Increase to a larger preview, similar in height to the download modal's full-width preview
- Applies to: `templates/stock_search.html` — `#ss-preview` and `#ss-img-section` CSS

### 2. Thumbnail URL caching

- `/thumbnail` makes one Graph API call per image per page load — will be slow for large libraries
- Cache the CDN redirect URL server-side (keyed by location path) with a ~45 min TTL (URLs expire in ~1 hour)
- Applies to: `src/app.py` `_serve_image()` and/or `src/sharepoint_client.py`

### 1. Welcome / Instructions Feature

- Add a welcome modal or banner that appears for first-time visitors (localStorage flag)
- Cover the key workflows: browsing/searching images, uploading new images, using stock search, managing tags
- Include a "Don't show again" / "Got it" dismiss button
- Applies to: `templates/index.html` (and possibly a shared include across all pages)

---

## Applied

### Add `/health` endpoint — deployed 2026-04-05
