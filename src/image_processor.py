"""Image processing pipeline: transform → AI metadata → store.

Used by Feature 2 (upload) and any future feature that catalogs an image.
"""

import re
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from PIL import Image as PILImage

from src.config import Config

# Matches specification.md — WebP output spec
WEBP_MAX_SIDE = 1600
WEBP_QUALITY = 80

CATEGORIES = ["Headshots", "Community", "Locations", "Situations", "Graphics", "Banners"]
SOURCES = ["ShutterStock", "AdobeStock", "Unsplash", "Pexels", "Pixabay", "Internal"]

_SOURCE_ALIASES = {
    "shutterstock": "ShutterStock",
    "adobestock": "AdobeStock",
    "adobe-stock": "AdobeStock",
    "adobe stock": "AdobeStock",
    "unsplash": "Unsplash",
    "pexels": "Pexels",
    "pixabay": "Pixabay",
    "internal": "Internal",
}


def normalize_source(source: Optional[str]) -> str:
    """Normalize free-form source values to a supported canonical source."""
    if not source:
        return "Internal"
    raw = source.strip()
    if raw in SOURCES:
        return raw
    key = re.sub(r"[^a-z0-9]+", "", raw.lower())
    return _SOURCE_ALIASES.get(key, "Internal")


# ---------------------------------------------------------------------------
# Image transformation
# ---------------------------------------------------------------------------

def transform_to_webp(image_bytes: bytes) -> bytes:
    """Convert raw image bytes to WebP.

    Scales down if the longest side exceeds WEBP_MAX_SIDE (never upscales).
    Preserves alpha channel for PNG/WebP sources.
    """
    with PILImage.open(BytesIO(image_bytes)) as img:
        # Preserve alpha where present; otherwise force RGB
        if img.mode in ("RGBA", "LA"):
            img = img.convert("RGBA")
        elif img.mode == "P" and "transparency" in img.info:
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        w, h = img.size
        longest = max(w, h)
        if longest > WEBP_MAX_SIDE:
            scale = WEBP_MAX_SIDE / longest
            img = img.resize((round(w * scale), round(h * scale)), PILImage.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=4)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def slug_from_text(text: str, max_len: int = 60) -> str:
    """Convert arbitrary text to a lowercase hyphenated slug (max 60 chars)."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len].rstrip("-") or "image"


def _unique_slug(base_slug: str, list_client) -> str:
    """Return base_slug, appending -2, -3, … until no matching record exists."""
    slug = base_slug
    counter = 2
    while list_client.record_exists(f"{slug}.webp"):
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def process_image(
    file_bytes: bytes,
    original_filename: str,
    generator,
    list_client,
    sp_client,
    image_folder: str,
    storage_mode: str,
    on_progress: Optional[Callable[[str], None]] = None,
    category: Optional[str] = None,
    source_context: Optional[str] = None,
    source: Optional[str] = None,
    write_high_res: bool = True,
    high_res_location_override: Optional[str] = None,
    initial_status: str = "pending-review",
    ingest_source: str = "",
) -> dict:
    """Full pipeline for a single image.

    Steps:
      1. Transform source bytes → WebP (resize to spec, quality 80)
      2. Generate alt text via Claude vision (max 125 chars)
      3. Generate tags via Claude vision (2–5 from approved vocabulary)
      4. Build unique slug from alt text
      5. Upload/save High-Res original and WebP output
      6. Create metadata record in list store

    Args:
        file_bytes:        Raw bytes of the source image.
        original_filename: Original filename (used to derive extension).
        category:          Storage category folder (e.g. "Headshots").
        generator:         AltTextGenerator instance.
        list_client:       LocalClient or SharePointListClient.
        sp_client:         SharePointClient or None (local mode).
        image_folder:      Local IMAGE_FOLDER path (used in local/test mode).
        storage_mode:      "sharepoint" or "local".
        on_progress:       Optional callback(msg) for SSE-style progress reporting.

    Returns:
        dict with keys: slug, filename, alt_text, tags, location,
                        high_res_location, status.

    Raises:
        Exception on any unrecoverable error.
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Must be one of: {CATEGORIES}")

    ext = Path(original_filename).suffix.lower() or ".jpg"
    source_name = normalize_source(source)

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    # ── Step 1: Transform ──────────────────────────────────────────────────
    _log("Transforming image to WebP…")
    webp_bytes = transform_to_webp(file_bytes)

    # ── Step 1b: Category (AI-determined if not supplied) ──────────────────
    if category is None:
        _log("Determining category via Claude…")
        category = generator.generate_category(webp_bytes, CATEGORIES, filename="image.webp")
        if category is None:
            category = "Situations"  # safe fallback
        _log(f"Category: {category}")

    # ── Step 2: Alt text ───────────────────────────────────────────────────
    _log("Generating alt text via Claude…")
    alt_text = generator.generate_alt_text(webp_bytes, context=source_context, filename="image.webp") or ""
    _log(f"Alt text: {alt_text}")

    # ── Step 3: Tags ───────────────────────────────────────────────────────
    _log("Generating tags via Claude…")
    tags = generator.generate_tags(webp_bytes, context=source_context, filename="image.webp") or ""
    _log(f"Tags: {tags}")

    # ── Step 4: Slug ───────────────────────────────────────────────────────
    base_slug = slug_from_text(alt_text[:80])
    slug = _unique_slug(base_slug, list_client)
    webp_filename = f"{slug}.webp"
    highres_filename = f"{slug}-original{ext}"
    location = f"{category}/{webp_filename}"
    high_res_location = high_res_location_override or f"{source_name}/{highres_filename}"

    # ── Steps 5a–5b: Store files ───────────────────────────────────────────
    if storage_mode == "sharepoint" and sp_client is not None:
        root = Config.SHAREPOINT_IMAGE_FOLDER
        hr_rel = PurePosixPath(high_res_location)
        if write_high_res:
            _log("Uploading High-Res to SharePoint…")
            hr_folder = f"{root}/High-Res/{hr_rel.parent}" if str(hr_rel.parent) != "." else f"{root}/High-Res"
            sp_client.upload_file(hr_folder, hr_rel.name, file_bytes)
        _log("Uploading WebP to SharePoint…")
        sp_client.upload_file(f"{root}/WebP/{category}", webp_filename, webp_bytes)
    else:
        base = Path(image_folder)
        _log("Saving files locally…")
        # Store under WebP/ to match the SharePoint folder convention
        webp_path = base / "WebP" / category / webp_filename
        webp_path.parent.mkdir(parents=True, exist_ok=True)
        webp_path.write_bytes(webp_bytes)

        if write_high_res:
            hr_path = base / "High-Res" / Path(high_res_location)
            hr_path.parent.mkdir(parents=True, exist_ok=True)
            hr_path.write_bytes(file_bytes)

    # ── Step 6: Metadata record ────────────────────────────────────────────
    _log("Writing metadata record…")
    record = list_client.create_record(
        filename=webp_filename,
        alt_text=alt_text,
        tags=tags,
        status=initial_status,
        slug=slug,
        location=location,
        high_res_location=high_res_location,
        source=source_name,
        ingest_source=ingest_source,
    )
    if not record:
        raise RuntimeError("Metadata record creation failed")

    _log("Done.")
    return {
        "slug": slug,
        "filename": webp_filename,
        "alt_text": alt_text,
        "tags": tags,
        "location": location,
        "high_res_location": high_res_location,
        "source": source_name,
        "status": initial_status,
    }
