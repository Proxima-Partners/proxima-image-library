#!/usr/bin/env python3
"""Record structured license data (sidecar ``rights``) for existing images.

Input is a JSON or CSV file. Values are merged with src.image_metadata.write_rights:
blank values never erase anything, existing non-empty values are kept unless
--force, and statements are appended. Never put guesses in the input — leave
unknown fields blank.

JSON: either {"<slug>": {<rights>}, ...} or [{"slug": "...", "rights": {...}}, ...]

CSV: one row per slug. Columns are rights field names (slug required).
    List fields (approvedChannels, restrictions, approvedCrops) use ";" separators.
    statement_by / statement_on / statement_text add one statement.
    verification_status / verification_verifiedBy / verification_verifiedOn /
    verification_evidence fill the verification object.

Dry-run by default (prints the per-slug change); pass --apply to write.

Usage:
    .venv/bin/python3 -m scripts.record_rights rights.json
    .venv/bin/python3 -m scripts.record_rights rights.csv --apply
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.config import Config
from src.image_metadata import read_rights, write_rights

_LIST_FIELDS = {"approvedChannels", "restrictions", "approvedCrops"}


def _row_to_rights(row: dict) -> dict:
    rights: dict = {}
    verification: dict = {}
    statement = {}
    for key, raw in row.items():
        value = (raw or "").strip()
        if key == "slug" or not value:
            continue
        if key.startswith("statement_"):
            statement[key.removeprefix("statement_")] = value
        elif key.startswith("verification_"):
            verification[key.removeprefix("verification_")] = value
        elif key in _LIST_FIELDS:
            rights[key] = [v.strip() for v in value.split(";") if v.strip()]
        else:
            rights[key] = value
    if statement:
        rights["statements"] = [statement]
    if verification:
        rights["verification"] = verification
    return rights


def load_entries(path: Path) -> list[tuple[str, dict]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [(row["slug"].strip(), _row_to_rights(row)) for row in csv.DictReader(handle) if row.get("slug")]
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [(slug, rights) for slug, rights in data.items()]
    return [(item["slug"], item["rights"]) for item in data]


def _diff(before: dict, after: dict) -> list[str]:
    lines = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            lines.append(f"    {key}: {json.dumps(before.get(key))} -> {json.dumps(after.get(key))}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="JSON or CSV file of rights patches")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing non-empty values")
    args = parser.parse_args()

    if Config.TEST_MODE:
        storage = {"storage_mode": "local", "image_folder": Config.IMAGE_FOLDER, "sp_client": None}
    else:
        from src.sharepoint_client import SharePointClient
        storage = {"storage_mode": "sharepoint", "image_folder": Config.IMAGE_FOLDER, "sp_client": SharePointClient()}

    entries = load_entries(args.input)
    print(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} from {args.input}"
          f" — {'APPLY' if args.apply else 'dry run'}{' (force)' if args.force else ''}\n")
    errors = 0
    for slug, patch in entries:
        try:
            before = (read_rights(slug, **storage) or {}).get("rights", {})
            result = write_rights(slug, patch, force=args.force, dry_run=not args.apply, **storage)
        except (FileNotFoundError, ValueError) as exc:
            errors += 1
            print(f"{slug}: ERROR {exc}")
            continue
        changes = _diff(before, result["rights"])
        print(f"{slug}: status={result['status']}, {len(changes)} change(s)")
        for line in changes:
            print(line)
        if result["conflicts"]:
            print(f"    kept existing (use --force to overwrite): {', '.join(result['conflicts'])}")
        print(f"    still missing: {', '.join(result['missing']) or 'nothing'}")

    print(f"\n{'Written' if args.apply else 'Dry run complete'}; {errors} error(s).")
    if not args.apply:
        print("Pass --apply to write.")


if __name__ == "__main__":
    main()
