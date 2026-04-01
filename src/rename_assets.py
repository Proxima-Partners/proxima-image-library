"""Batch rename image assets using a consistent naming convention.

Default format:
    {prefix}-{index:04d}-{slug}.{ext}

Examples:
    proxima-0001-square-katie-web4.webp
    proxima-0002-ways-to-give-legacy.png
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

from src.image_scanner import ImageScanner


def slugify(value: str) -> str:
    """Convert a filename stem to a safe lowercase slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "image"


def build_plan(
    images: List[Tuple[str, str]],
    prefix: str,
    start_index: int,
) -> List[Tuple[Path, Path]]:
    """Create a collision-safe rename plan.

    Returns a list of (source_path, target_path).
    """
    sorted_images = sorted(images, key=lambda pair: pair[1].lower())
    used_targets: Dict[Path, int] = {}
    plan: List[Tuple[Path, Path]] = []

    for offset, (full_path, _relative_path) in enumerate(sorted_images):
        source = Path(full_path)
        extension = source.suffix.lower()
        stem_slug = slugify(source.stem)
        base_name = f"{prefix}-{start_index + offset:04d}-{stem_slug}"

        candidate = source.with_name(f"{base_name}{extension}")
        if candidate == source:
            continue

        # Resolve collisions if two files normalize to same target.
        if candidate in used_targets or (candidate.exists() and candidate != source):
            collision_count = used_targets.get(candidate, 1)
            while True:
                candidate = source.with_name(f"{base_name}-{collision_count}{extension}")
                if candidate not in used_targets and (not candidate.exists() or candidate == source):
                    break
                collision_count += 1
            used_targets[candidate] = collision_count + 1
        else:
            used_targets[candidate] = 1

        plan.append((source, candidate))

    return plan


def write_mapping(mapping_file: Path, rename_plan: List[Tuple[Path, Path]]) -> None:
    """Write a CSV mapping of old and new paths for auditing."""
    with mapping_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["old_path", "new_path"])
        for old_path, new_path in rename_plan:
            writer.writerow([str(old_path), str(new_path)])


def execute_plan(rename_plan: List[Tuple[Path, Path]]) -> None:
    """Execute the rename plan in a safe order."""
    for old_path, new_path in rename_plan:
        old_path.rename(new_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch rename asset images")
    parser.add_argument(
        "--prefix",
        default="proxima",
        help="Filename prefix used in renamed files (default: proxima)",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="Starting index for numbering (default: 1)",
    )
    parser.add_argument(
        "--mapping-file",
        default="rename_map.csv",
        help="CSV file to write old/new filename mappings (default: rename_map.csv)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply renames (default is dry-run)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scanner = ImageScanner()
    images = scanner.get_all_images()

    if not images:
        print("No images found. Nothing to rename.")
        return

    plan = build_plan(images, args.prefix, args.start_index)
    mapping_path = Path(args.mapping_file).resolve()
    write_mapping(mapping_path, plan)

    print(f"Found {len(images)} image(s)")
    print(f"Planned rename operations: {len(plan)}")
    print(f"Mapping file: {mapping_path}")

    preview_count = min(10, len(plan))
    if preview_count:
        print("\nPreview:")
        for old_path, new_path in plan[:preview_count]:
            print(f"- {old_path.name} -> {new_path.name}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to perform renames.")
        return

    execute_plan(plan)
    print(f"\nDone. Renamed {len(plan)} file(s).")


if __name__ == "__main__":
    main()
