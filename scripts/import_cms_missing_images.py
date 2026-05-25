"""Import CMS image references (from audit report) into the library pipeline.

Default mode is dry-run. Use --apply to execute writes.

Example:
  TEST_MODE=false STORAGE_MODE=sharepoint PYTHONPATH=. \
  .venv/bin/python3 scripts/import_cms_missing_images.py --apply
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from src.config import Config
from src.ai_generator import AltTextGenerator
from src.image_processor import process_image
from src.local_client import LocalClient
from src.sharepoint_client import SharePointClient
from src.sharepoint_list_client import SharePointListClient


DEFAULT_REPORT = Path("test_data/cms_library_audit_report.json")


def _filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(unquote(parsed.path or "")).name.strip()
    if not name:
        return "cms-image.jpg"
    # Keep extension for content validation; trim extreme lengths.
    if len(name) > 180:
        stem = Path(name).stem[:140]
        suffix = Path(name).suffix or ".jpg"
        return f"{stem}{suffix}"
    return name


def _load_missing(report_path: Path) -> list[dict]:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    missing = data.get("missing", [])
    if not isinstance(missing, list):
        return []
    return [m for m in missing if isinstance(m, dict) and str(m.get("url", "")).strip()]


def _get_clients():
    if Config.TEST_MODE:
        return LocalClient(), None, "local"
    return SharePointListClient(), SharePointClient(), "sharepoint"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import missing CMS images into the library")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Path to cms_library_audit_report.json")
    parser.add_argument("--apply", action="store_true", help="Execute writes (default is dry-run)")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"ERROR: report file not found: {report_path}")
        return 2

    missing = _load_missing(report_path)
    if not missing:
        print("No missing CMS image references found in report.")
        return 0

    print(f"Missing references in report: {len(missing)}")
    if not args.apply:
        print("Dry-run mode. Use --apply to import.")
        for row in missing[:20]:
            print(f"- [{row.get('collection_name','?')}] {row.get('item_name','?')} -> {row.get('url','')}")
        if len(missing) > 20:
            print(f"... and {len(missing) - 20} more")
        return 0

    list_client, sp_client, storage_mode = _get_clients()
    generator = AltTextGenerator()

    imported = 0
    failed = 0
    failures: list[dict] = []

    for idx, row in enumerate(missing, start=1):
        url = str(row.get("url", "") or "").strip()
        if not url:
            continue
        filename = _filename_from_url(url)
        title = str(row.get("item_name", "") or "").strip() or filename

        print(f"[{idx}/{len(missing)}] Importing {title}")

        try:
            resp = requests.get(url, timeout=45)
            resp.raise_for_status()
            file_bytes = resp.content

            process_image(
                file_bytes=file_bytes,
                original_filename=filename,
                generator=generator,
                list_client=list_client,
                sp_client=sp_client,
                image_folder=Config.IMAGE_FOLDER,
                storage_mode=storage_mode,
                category=None,
                source_context=(
                    "Imported from CMS reference audit. "
                    f"Collection: {row.get('collection_name','')}. "
                    f"Item: {title}."
                ),
                source="Internal",
                ingest_source="cms-audit-import",
            )
            imported += 1
        except Exception as e:
            failed += 1
            failures.append({
                "url": url,
                "item_name": title,
                "error": str(e),
            })
            print(f"  FAILED: {e}")

    out = {
        "total_missing": len(missing),
        "imported": imported,
        "failed": failed,
        "failures": failures,
    }
    out_path = Path("test_data/cms_library_import_report.json")
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\nImport complete")
    print(json.dumps(out, indent=2))
    print(f"Report written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
