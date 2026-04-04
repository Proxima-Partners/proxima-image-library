"""Migrate records from local JSON store to SharePoint List.

Maps existing Location paths to the new category folder structure and writes
each record to the SharePoint Assets list.

Usage (run from project root):
    python3 -m scripts.migrate_records              # live run
    python3 -m scripts.migrate_records --dry-run    # preview only
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from src.sharepoint_list_client import SharePointListClient


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

def map_to_category(location: str, tags: str) -> str:
    """Determine the new category folder from the old location path and tags."""
    tag_set = {t.strip().lower() for t in tags.split(",") if t.strip()}
    loc = location.lower()

    # Folder-based signals first (most reliable)
    if "headshots" in loc:
        return "Headshots"

    # Emotion/situation tags take priority over content-type tags
    if tag_set & {"hardship", "loneliness", "prayer", "unhoused"}:
        return "Situations"

    # Graphic assets — specific indicators only (not the generic "graphic" tag)
    if tag_set & {"icon", "logo", "illustration", "vector"}:
        return "Graphics"

    # "graphic" alone (designed/stylised image with no stronger signal) → Graphics
    if "graphic" in tag_set and not tag_set & {"people", "individual", "group", "outdoor", "indoor"}:
        return "Graphics"

    # SF / landscape / architecture with no people
    people_tags = {
        "people", "individual", "group", "headshot", "staff",
        "volunteer", "family", "youth", "elderly", "unhoused",
        "neighbor", "community",
    }
    location_signals = {
        "san-francisco", "landscape", "architecture", "bridge",
        "waterfront", "golden-gate", "bay-area",
    }
    if tag_set & location_signals and not tag_set & people_tags:
        return "Locations"

    # Banner / background images with no people
    if tag_set & {"banner", "background"} and not tag_set & people_tags:
        return "Banners"

    # Default — anything with people or community context
    return "Community"


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate(dry_run: bool = False) -> None:
    source = Path("test_data/local_table.json")
    if not source.exists():
        print(f"Error: {source} not found — run from project root.")
        sys.exit(1)

    with source.open(encoding="utf-8") as f:
        records = json.load(f)

    print(f"{'[DRY RUN] ' if dry_run else ''}Migrating {len(records)} records to SharePoint List...\n")

    client = None if dry_run else SharePointListClient()

    migrated = 0
    failed = 0

    for i, record in enumerate(records, 1):
        fields = record.get("fields", {})
        filename = fields.get("Filename", "").strip()
        if not filename:
            continue

        location = fields.get("Location", "")
        tags     = fields.get("Tags", "")
        slug     = fields.get("Slug", "")
        alt_text = fields.get("Alt Text", "")
        status   = fields.get("Status", "pending-review")

        category = map_to_category(location, tags)
        ext      = Path(filename).suffix.lower()

        # WebP delivery path (what the app serves)
        webp_name = f"{slug}.webp" if slug else filename
        new_location = f"{category}/{webp_name}"

        # High-Res path (original file, untransformed)
        new_high_res = f"{category}/{filename}"

        print(f"[{i:>3}/{len(records)}] {filename}")
        print(f"         {location!r:40s} → {category}/")

        if dry_run:
            print(f"         location={new_location}")
            print(f"         high_res={new_high_res}\n")
            migrated += 1
            continue

        result = client.create_record(
            filename=filename,
            alt_text=alt_text,
            tags=tags,
            status=status,
            slug=slug,
            location=new_location,
            high_res_location=new_high_res,
        )

        if result:
            migrated += 1
            print(f"         ✓ id={result['id']}\n")
        else:
            failed += 1
            print(f"         ✗ failed\n")

    print("-" * 60)
    print(f"Done. {migrated} migrated, {failed} failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate records to SharePoint List")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
