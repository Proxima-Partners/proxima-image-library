"""Upload local images to SharePoint High-Res/ and WebP/ folders.

For each image in IMAGE_FOLDER:
  - Uploads the original to   Images/High-Res/{category}/{filename}
  - Converts to WebP and uploads to  Images/WebP/{category}/{slug}.webp

Category is determined from the record's tags in test_data/local_table.json.
Images with no matching record fall back to Community/.

Usage (run from project root):
    python3 -m scripts.migrate_files              # live run
    python3 -m scripts.migrate_files --dry-run    # preview only
    python3 -m scripts.migrate_files --skip-webp  # High-Res only
"""

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from PIL import Image as PILImage

from src.config import Config
from src.sharepoint_client import SharePointClient
from scripts.migrate_records import map_to_category


# ---------------------------------------------------------------------------
# WebP conversion
# ---------------------------------------------------------------------------

def to_webp_bytes(image_path: Path) -> bytes:
    """Convert an image to WebP per specification (longest side ≤1600px, q80)."""
    with PILImage.open(image_path) as img:
        w, h = img.size
        longest = max(w, h)
        if longest > 1600:
            scale = 1600 / longest
            img = img.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)

        # Preserve alpha for PNG/WebP; convert everything else to RGB
        if img.mode in ("RGBA", "LA", "PA"):
            img = img.convert("RGBA")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        buf = BytesIO()
        img.save(buf, format="WEBP", quality=80)
        buf.seek(0)
        return buf.read()


# ---------------------------------------------------------------------------
# Build filename → record lookup from local JSON
# ---------------------------------------------------------------------------

def load_record_index() -> dict:
    """Return {filename: fields} from local_table.json."""
    path = Path("test_data/local_table.json")
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        records = json.load(f)
    return {r["fields"].get("Filename", ""): r["fields"] for r in records}


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate(dry_run: bool = False, skip_webp: bool = False) -> None:
    image_folder = Path(Config.IMAGE_FOLDER)
    if not image_folder.exists():
        print(f"Error: IMAGE_FOLDER not found: {image_folder}")
        sys.exit(1)

    formats = {
        f if f.startswith(".") else f".{f}"
        for f in Config.SUPPORTED_FORMATS
    }

    images = [p for p in image_folder.rglob("*") if p.is_file() and p.suffix.lower() in formats]
    print(f"{'[DRY RUN] ' if dry_run else ''}Found {len(images)} images in {image_folder}\n")

    record_index = load_record_index()
    sp = None if dry_run else SharePointClient()
    root = Config.SHAREPOINT_IMAGE_FOLDER  # "Images"

    uploaded = 0
    failed   = 0
    skipped  = 0

    for i, image_path in enumerate(sorted(images), 1):
        filename = image_path.name
        fields   = record_index.get(filename, {})
        tags     = fields.get("Tags", "")
        slug     = fields.get("Slug", "")
        location = fields.get("Location", "")

        category = map_to_category(location, tags)

        high_res_sp_path = f"{root}/High-Res/{category}"
        webp_name        = f"{slug}.webp" if slug else f"{Path(filename).stem}.webp"
        webp_sp_path     = f"{root}/WebP/{category}"

        print(f"[{i:>3}/{len(images)}] {filename} → {category}/")

        if dry_run:
            print(f"         High-Res: {high_res_sp_path}/{filename}")
            if not skip_webp:
                print(f"         WebP:     {webp_sp_path}/{webp_name}")
            print()
            uploaded += 1
            continue

        # --- Upload original to High-Res ---
        try:
            original_bytes = image_path.read_bytes()
            sp.upload_file(high_res_sp_path, filename, original_bytes)
            print(f"         ✓ High-Res uploaded ({len(original_bytes) / 1024:.0f} KB)")
        except Exception as e:
            print(f"         ✗ High-Res failed: {e}")
            failed += 1
            continue

        # --- Convert and upload WebP ---
        if not skip_webp:
            try:
                webp_bytes = to_webp_bytes(image_path)
                sp.upload_file(webp_sp_path, webp_name, webp_bytes)
                print(f"         ✓ WebP uploaded ({len(webp_bytes) / 1024:.0f} KB)")
            except Exception as e:
                print(f"         ✗ WebP failed: {e}")
                # Non-fatal — High-Res is already uploaded

        uploaded += 1
        print()

    print("-" * 60)
    print(f"Done. {uploaded} uploaded, {failed} failed, {skipped} skipped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate image files to SharePoint")
    parser.add_argument("--dry-run",   action="store_true", help="Preview without uploading")
    parser.add_argument("--skip-webp", action="store_true", help="Upload High-Res only, skip WebP conversion")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run, skip_webp=args.skip_webp)
