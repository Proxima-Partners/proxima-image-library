"""Non-destructive backfill of PNG twins for existing standard/hero WebP derivatives.

New uploads get PNGs from process_image(). This module brings the existing
catalog up to the same shape: for each record with a sidecar, it writes
PNG/<category>/<slug>.png (and Hero-PNG/... when the record has a hero) and
sets only ``standard.png`` / ``hero.png`` in the sidecar. Every other sidecar
key — rights, original, focalPoint — is left untouched.
"""

from io import BytesIO

from PIL import Image as PILImage

from src.hero_backfill import _asset_exists, _read_asset, _safe_relative, _write_asset
from src.image_metadata import read_metadata, write_metadata
from src.image_processor import convert_to_png, generate_web_derivatives, png_location, png_meta


def needs_png(metadata: dict) -> bool:
    """True when a sidecar's standard (or existing hero) lacks a PNG entry."""
    if not isinstance(metadata, dict) or not metadata:
        return False
    standard = metadata.get("standard") if isinstance(metadata.get("standard"), dict) else {}
    hero = metadata.get("hero") if isinstance(metadata.get("hero"), dict) else None
    if standard.get("location") and not standard.get("png"):
        return True
    return bool(hero and hero.get("location") and not hero.get("png"))


def _write_png(area: str, location: str, derivative: dict, *, force: bool, storage_mode, image_folder, sp_client) -> tuple[dict, bool]:
    exists = _asset_exists(area, location, storage_mode=storage_mode, image_folder=image_folder, sp_client=sp_client)
    if not exists or force:
        _write_asset(area, location, derivative["bytes"], storage_mode=storage_mode, image_folder=image_folder, sp_client=sp_client)
    return png_meta(derivative, location), (not exists or force)


def write_png_derivatives(
    derivatives: dict,
    *,
    standard_location: str,
    hero_location: str,
    storage_mode: str,
    image_folder: str,
    sp_client=None,
    force: bool = False,
) -> dict:
    """Store PNG derivatives produced by generate_web_derivatives().

    Existing PNG files are kept unless force=True. Returns sidecar entries
    for standard/hero (None when not applicable) and the areas written.
    """
    result = {"standard": None, "hero": None, "created": [], "bytesWritten": 0}
    targets = (
        ("standard", "PNG", standard_location, derivatives.get("standard_png")),
        ("hero", "Hero-PNG", hero_location, derivatives.get("hero_png")),
    )
    for key, area, webp_location, derivative in targets:
        if not webp_location or not derivative:
            continue
        location = png_location(_safe_relative(webp_location))
        meta, written = _write_png(
            area, location, derivative, force=force,
            storage_mode=storage_mode, image_folder=image_folder, sp_client=sp_client,
        )
        result[key] = meta
        if written:
            result["created"].append(area)
            result["bytesWritten"] += derivative["fileSize"]
    return result


def _png_from_webp(webp_bytes: bytes) -> dict:
    content = convert_to_png(webp_bytes)
    with PILImage.open(BytesIO(content)) as img:
        width, height = img.size
    return {"bytes": content, "width": width, "height": height, "format": "PNG", "fileSize": len(content)}


def backfill_png(
    record: dict,
    *,
    storage_mode: str,
    image_folder: str,
    sp_client=None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Backfill PNG twins for one catalog record.

    Renders from the High-Res original with the same resize as uploads; if
    the original is unavailable, converts the stored WebP derivatives instead
    (``pngSource: "webp"``). Records without a sidecar are skipped — run the
    hero backfill for those first.
    """
    fields = record.get("fields", {})
    slug = str(fields.get("Slug", "") or "").strip()
    result = {
        "id": str(record.get("id", "")),
        "slug": slug,
        "status": "skipped",
        "standardPng": "n/a",
        "heroPng": "n/a",
        "pngSource": "",
        "bytesWritten": 0,
    }
    if not slug:
        result["reason"] = "no-slug"
        return result
    metadata = read_metadata(slug, storage_mode=storage_mode, image_folder=image_folder, sp_client=sp_client)
    if not metadata:
        result["reason"] = "no-sidecar (run hero backfill first)"
        return result
    if not force and not needs_png(metadata):
        result.update(status="exists", standardPng="exists", heroPng="exists" if metadata.get("hero") else "n/a")
        return result

    standard = metadata.get("standard") if isinstance(metadata.get("standard"), dict) else {}
    hero = metadata.get("hero") if isinstance(metadata.get("hero"), dict) else None
    standard_location = standard.get("location") or str(fields.get("Location", "") or "")
    hero_location = (hero or {}).get("location", "")
    if dry_run:
        result.update(
            status="planned",
            standardPng="planned" if standard_location else "n/a",
            heroPng="planned" if hero_location else "n/a",
        )
        return result

    storage = {"storage_mode": storage_mode, "image_folder": image_folder, "sp_client": sp_client}
    original_location = (metadata.get("original") or {}).get("location") or fields.get("High-Res Location", "")
    try:
        original_bytes = _read_asset("High-Res", original_location, **storage)
        derivatives = generate_web_derivatives(original_bytes)
        result["pngSource"] = "original"
    except Exception:
        derivatives = {
            "standard_png": _png_from_webp(_read_asset("WebP", standard_location, **storage)) if standard_location else None,
            "hero_png": _png_from_webp(_read_asset("Hero", hero_location, **storage)) if hero_location else None,
        }
        result["pngSource"] = "webp"
    if not hero_location:
        derivatives["hero_png"] = None

    written = write_png_derivatives(
        derivatives,
        standard_location=standard_location,
        hero_location=hero_location,
        force=force,
        **storage,
    )

    # Re-read right before writing so the window for clobbering a concurrent
    # sidecar edit (e.g. a rights update) stays as small as possible.
    latest = read_metadata(slug, **storage) or metadata
    if written["standard"] and isinstance(latest.get("standard"), dict):
        latest["standard"] = {**latest["standard"], "png": written["standard"]}
    if written["hero"] and isinstance(latest.get("hero"), dict):
        latest["hero"] = {**latest["hero"], "png": written["hero"]}
    write_metadata(latest, **storage)

    result.update(
        status="done",
        standardPng=("created" if "PNG" in written["created"] else "exists") if written["standard"] else "n/a",
        heroPng=("created" if "Hero-PNG" in written["created"] else "exists") if written["hero"] else "n/a",
        bytesWritten=written["bytesWritten"],
    )
    return result
