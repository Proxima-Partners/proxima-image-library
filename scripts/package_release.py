#!/usr/bin/env python3
"""Create a source-only ZIP for Azure Oryx; no secrets, Git, tests or venvs."""

import argparse
import json
import re
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {"src", "scripts", "templates", "static"}
ROOT_FILES = {"requirements.txt", "runtime.txt", "startup.sh"}
REQUIRED = ROOT_FILES | {"src/app.py", "src/telemetry.py", "templates/index.html"}


def package_release(output, *, root=ROOT, commit=None):
    root = Path(root)
    commit = commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full commit SHA")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    files = sorted(name for name in tracked if name and (
        name in ROOT_FILES or Path(name).parts[0] in DIRECTORIES
    ) and not any(part.startswith(".") or part == "__pycache__" for part in Path(name).parts))
    if missing := REQUIRED - set(files):
        raise ValueError(f"Missing required release files: {sorted(missing)}")
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name in files:
            path = root / name
            if path.is_symlink():
                raise ValueError(f"Symlinks are not allowed in release: {name}")
            archive.write(path, name)
        archive.writestr("build_info.json", json.dumps({"commit": commit}))
    return len(files) + 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    count = package_release(args.output)
    print(f"Packaged {count} files ({args.output.stat().st_size:,} bytes)")
