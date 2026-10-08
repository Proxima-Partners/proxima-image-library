#!/usr/bin/env python3
"""Backfill PNG twins (PNG/ and Hero-PNG/) for images cataloged before PNG support.

New uploads already get PNGs from process_image(). This brings the existing
library to the same shape using src.png_backfill.backfill_png, which only
writes missing PNG files and only sets standard.png / hero.png in each
sidecar (rights, original and focalPoint are never touched).

Dry-run by default: reports candidates, records with no High-Res original
(those fall back to converting the stored WebP), and an estimate of the
storage the PNGs will add. Pass --apply to write.

Usage:
    .venv/bin/python3 -m scripts.run_png_backfill                              # preview, all statuses
    .venv/bin/python3 -m scripts.run_png_backfill --apply --limit 10 --status approved   # pilot
    .venv/bin/python3 -m scripts.run_png_backfill --apply --status approved    # approved records
    .venv/bin/python3 -m scripts.run_png_backfill --apply                      # everything else
    .venv/bin/python3 -m scripts.run_png_backfill --apply --slug some-slug     # retry one record
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.config import Config
from src.hero_backfill import _read_asset
from src.image_metadata import read_metadata
from src.image_processor import generate_web_derivatives
from src.png_backfill import backfill_png

REPORT_DIR = Path(__file__).parent.parent / "test_data" / "png_backfill_reports"
ESTIMATE_SAMPLE = 5
PAUSE_SECONDS = 0.5  # stay well under Graph throttling limits


def _clients():
    if Config.TEST_MODE:
        from src.local_client import LocalClient
        return LocalClient(), None, "local"
    from src.sharepoint_client import SharePointClient
    from src.sharepoint_list_client import SharePointListClient
    return SharePointListClient(), SharePointClient(), "sharepoint"


def _format_mb(num_bytes: float) -> str:
    return f"{num_bytes / 1_048_576:,.1f} MB"


def _estimate(candidates: list[dict], storage: dict) -> str:
    """Encode PNGs for a small sample in memory and extrapolate. Writes nothing."""
    sizes, hero_sizes = [], []
    for record in candidates[:ESTIMATE_SAMPLE]:
        slug = record["fields"].get("Slug", "")
        metadata = read_metadata(slug, **storage)
        location = (metadata.get("original") or {}).get("location") or record["fields"].get("High-Res Location", "")
        try:
            derivatives = generate_web_derivatives(_read_asset("High-Res", location, **storage))
        except Exception:
            continue
        sizes.append(derivatives["standard_png"]["fileSize"])
        if derivatives["hero_png"] and metadata.get("hero"):
            hero_sizes.append(derivatives["hero_png"]["fileSize"])
    if not sizes:
        return "no sample could be measured"
    hero_count = sum(1 for r in candidates if r.get("_hasHero"))
    avg = sum(sizes) / len(sizes)
    hero_avg = sum(hero_sizes) / len(hero_sizes) if hero_sizes else 0
    total = avg * len(candidates) + hero_avg * hero_count
    return (
        f"~{_format_mb(total)} (standard avg {_format_mb(avg)} × {len(candidates)}"
        f"{f', hero avg {_format_mb(hero_avg)} × {hero_count}' if hero_count else ''}; "
        f"sample of {len(sizes)})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", default="", help="Only records with this Status (default: all)")
    parser.add_argument("--slug", action="append", default=[], help="Only this slug (repeatable)")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N candidates")
    parser.add_argument("--force", action="store_true", help="Rewrite PNGs that already exist")
    parser.add_argument("--apply", action="store_true", help="Write PNGs (default: dry run)")
    args = parser.parse_args()

    list_client, sp_client, storage_mode = _clients()
    storage = {"storage_mode": storage_mode, "image_folder": Config.IMAGE_FOLDER, "sp_client": sp_client}

    records = list_client.get_all_records()
    status_filter = args.status.strip().lower()
    if status_filter:
        records = [r for r in records if str(r.get("fields", {}).get("Status", "") or "").strip().lower() == status_filter]
    if args.slug:
        wanted = set(args.slug)
        records = [r for r in records if r.get("fields", {}).get("Slug") in wanted]
    print(f"Scanning {len(records)} record(s){f' with Status={status_filter!r}' if status_filter else ''}...")

    candidates, skipped, existing = [], [], 0
    for record in records:
        plan = backfill_png(record, force=args.force, dry_run=True, **storage)
        if plan["status"] == "planned":
            record["_hasHero"] = plan["heroPng"] == "planned"
            candidates.append(record)
        elif plan["status"] == "exists":
            existing += 1
        else:
            skipped.append(plan)
    if args.limit > 0:
        candidates = candidates[: args.limit]

    print(f"Already have PNGs: {existing}")
    print(f"Need PNGs: {len(candidates)}{' (limited)' if args.limit else ''} "
          f"— with hero: {sum(1 for r in candidates if r.get('_hasHero'))}")
    if skipped:
        print(f"Skipped: {len(skipped)}")
        for item in skipped[:20]:
            print(f"  {item['slug'] or item['id']}: {item.get('reason', '')}")
        if len(skipped) > 20:
            print(f"  … and {len(skipped) - 20} more")

    if not args.apply:
        if candidates:
            print(f"Estimated storage added: {_estimate(candidates, storage)}")
        print("\nDry run only — pass --apply to write PNG derivatives.")
        return
    if not candidates:
        print("\nNothing to backfill.")
        return

    print(f"\nWriting PNGs for {len(candidates)} record(s)...")
    results, failed, total_bytes, from_webp = [], 0, 0, 0
    for index, record in enumerate(candidates, 1):
        slug = record["fields"].get("Slug", "")
        try:
            result = backfill_png(record, force=args.force, **storage)
            total_bytes += result["bytesWritten"]
            from_webp += int(result["pngSource"] == "webp")
            print(f"[{index}/{len(candidates)}] OK {slug} (standard={result['standardPng']}, "
                  f"hero={result['heroPng']}, from={result['pngSource']})")
        except Exception as exc:
            failed += 1
            result = {"id": record.get("id"), "slug": slug, "status": "failed", "error": str(exc)}
            print(f"[{index}/{len(candidates)}] FAILED {slug}: {exc}")
        results.append(result)
        time.sleep(PAUSE_SECONDS)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"png_backfill_{datetime.now():%Y%m%d-%H%M%S}.json"
    report_path.write_text(json.dumps({
        "storageMode": storage_mode,
        "statusFilter": status_filter or "all",
        "force": args.force,
        "processed": len(candidates),
        "failed": failed,
        "fromWebpFallback": from_webp,
        "bytesWritten": total_bytes,
        "results": results,
    }, indent=2))
    print(f"\nDone. {len(candidates) - failed} succeeded, {failed} failed, "
          f"{from_webp} rendered from WebP (no original), {_format_mb(total_bytes)} written.")
    print(f"Report: {report_path}")
    if failed:
        print("Retry failures with: --apply --slug <slug>")


if __name__ == "__main__":
    main()
