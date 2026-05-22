"""Regenerate AI tags for all approved/pending-review records using the current tag vocabulary."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.ai_generator import AltTextGenerator
from src.config import Config
from src.sharepoint_client import SharePointClient
from src.sharepoint_list_client import SharePointListClient

TARGET_STATUSES = {"approved", "pending-review"}

client = SharePointListClient()
sp = SharePointClient()
gen = AltTextGenerator()

records = client.get_all_records()
targets = [
    r for r in records
    if r.get("fields", {}).get("Status", "").lower() in TARGET_STATUSES
]

print(f"Records to retag: {len(targets)}")
print("=" * 60)

processed = failed = skipped = 0

for idx, rec in enumerate(targets, 1):
    fields = rec.get("fields", {})
    rec_id = str(rec.get("id", "")).strip()
    filename = fields.get("Filename", "") or "unknown"
    location = fields.get("Location", "") or ""

    if not location:
        print(f"[{idx}/{len(targets)}] SKIP (no location): {filename}")
        skipped += 1
        continue

    print(f"[{idx}/{len(targets)}] {filename}", end=" ... ", flush=True)

    try:
        root = (Config.SHAREPOINT_IMAGE_FOLDER or "").strip().strip("/")
        webp_path = f"{root}/WebP/{location}" if root else f"WebP/{location}"
        file_bytes = sp.get_file_bytes(webp_path)

        new_tags = gen.generate_tags(file_bytes, filename=filename) or ""

        if new_tags:
            client.patch_fields(rec_id, {"Tags": new_tags})
            print(f"OK → {new_tags[:80]}")
            processed += 1
        else:
            print("SKIP (no tags returned)")
            skipped += 1

    except Exception as e:
        print(f"FAIL: {e}")
        failed += 1

print("=" * 60)
print(f"Done — processed: {processed}, skipped: {skipped}, failed: {failed}")
