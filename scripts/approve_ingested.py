"""One-off script: bulk-update all 'ingested' records to 'approved'."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.sharepoint_list_client import SharePointListClient

client = SharePointListClient()
records = client.get_all_records()

ingested = [r for r in records if r.get("fields", {}).get("Status", "").lower() == "ingested"]

if not ingested:
    print("No ingested records found.")
else:
    print(f"Found {len(ingested)} ingested records. Updating to approved...")
    patches = [(r["id"], {"Status": "approved"}) for r in ingested]
    client.bulk_patch_fields(patches)
    print(f"Done — {len(patches)} records approved.")
