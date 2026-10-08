#!/usr/bin/env python3
"""Print RIGHTS.md record tables for library images, read from GET /api/mcp/rights.

Used to regenerate Proxima-Brand-System/04-Photography/RIGHTS.md entries from
the library instead of hand-copying. Blank values print as "unknown"; nothing
is inferred. Read-only.

Usage:
    .venv/bin/python3 -m scripts.export_rights_md women-talking friends-conversation
    .venv/bin/python3 -m scripts.export_rights_md --base-url https://library.liveproxima.org women-talking
"""

import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.config import Config


def _value(value) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "unknown"
    text = str(value or "").strip()
    return text or "unknown"


def record_table(info: dict) -> str:
    rights = info.get("rights") or {}
    verification = rights.get("verification") or {}
    release = f"model: {_value(rights.get('modelRelease'))}; property: {_value(rights.get('propertyRelease'))}"
    if rights.get("releaseLocation"):
        release += f"; stored at {rights['releaseLocation']}"
    license_text = _value(rights.get("licenseType"))
    if rights.get("licenseReference"):
        license_text += f", ref {rights['licenseReference']}"
    if rights.get("licensedOn"):
        license_text += f", licensed {rights['licensedOn']}"
    if rights.get("licensee"):
        license_text += f" to {rights['licensee']}"
    reviewer = _value(verification.get("verifiedBy"))
    if verification.get("verifiedOn"):
        reviewer += f" on {verification['verifiedOn']}"
    rows = [
        ("Asset ID", f"{_value(rights.get('assetId'))} (provider ID: {_value(rights.get('providerAssetId'))})"),
        ("Filename", _value(info.get("filename"))),
        ("Photographer/source", f"{_value(rights.get('contributor'))} / {_value(rights.get('source') or info.get('source'))}"),
        ("Ownership or license", license_text),
        ("Consent/model release", release),
        ("Approved channels", _value(rights.get("approvedChannels"))),
        ("Expiration", _value(rights.get("expiration"))),
        ("Restrictions", _value(rights.get("restrictions"))),
        ("Approved crop", _value(rights.get("approvedCrops"))),
        ("Reviewer", reviewer),
        ("Verification", f"{_value(verification.get('status'))}; evidence: {_value(verification.get('evidence'))}"),
    ]
    lines = [f"### {info.get('slug')} ({info.get('status')})", "", "| Field | Record |", "|---|---|"]
    lines += [f"| {field} | {text.replace('|', '/')} |" for field, text in rows]
    for statement in rights.get("statements") or []:
        lines.append(f"\nStatement ({statement['on']}, {statement['by']}): {statement['text']}")
    if info.get("missing"):
        lines.append(f"\nStill missing: {', '.join(info['missing'])}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slugs", nargs="+")
    parser.add_argument("--base-url", default=Config.APP_BASE_URL)
    args = parser.parse_args()
    if not Config.MCP_INTERNAL_SECRET:
        sys.exit("MCP_INTERNAL_SECRET is not set")

    base = args.base_url.rstrip("/")
    for slug in args.slugs:
        resp = requests.get(
            f"{base}/api/mcp/rights",
            params={"slug": slug},
            headers={"X-MCP-Secret": Config.MCP_INTERNAL_SECRET},
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"### {slug}\n\nError {resp.status_code}: {resp.json().get('error', '') if resp.content else ''}\n")
            continue
        print(record_table(resp.json()) + "\n")


if __name__ == "__main__":
    main()
