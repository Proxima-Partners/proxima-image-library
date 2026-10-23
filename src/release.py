"""Immutable release identity, resolved once (never shell out per request)."""

import json
import re
import subprocess
from pathlib import Path

from src import __version__


def release_info(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    try:
        sha = json.loads((root / "build_info.json").read_text())["commit"]
    except (OSError, ValueError, KeyError, TypeError):
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True,
                stderr=subprocess.DEVNULL, timeout=2,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            sha = "unknown"
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        sha = "unknown"
    return {"version": __version__, "commit": sha, "short": sha[:7]}
