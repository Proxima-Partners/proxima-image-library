"""Audit Webflow CMS image usage against Image Library records.

Usage:
  .venv/bin/python3 scripts/audit_cms_images_vs_library.py

Required env vars:
  WEBFLOW_API_TOKEN
  WEBFLOW_SITE_ID

Optional env var:
  WEBFLOW_API_BASE (defaults to https://api.webflow.com)

Output:
  Writes JSON report to test_data/cms_library_audit_report.json
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from src.config import Config
from src.local_client import LocalClient
from src.sharepoint_list_client import SharePointListClient


IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|avif|svg)(?:$|[?#])", re.IGNORECASE)


@dataclass
class LibraryIndex:
    filenames: set[str]
    slugs: set[str]
    locations: set[str]


def _webflow_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "accept-version": "1.0.0",
        "Content-Type": "application/json",
    }


def _looks_like_image_url(value: str) -> bool:
    if not value.startswith(("http://", "https://")):
        return False
    if IMAGE_EXT_RE.search(value):
        return True
    return "images" in value.lower() and "webflow" in value.lower()


def _extract_image_urls(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        for _, value in node.items():
            _extract_image_urls(value, out)
        return
    if isinstance(node, list):
        for value in node:
            _extract_image_urls(value, out)
        return
    if isinstance(node, str):
        text = node.strip()
        if _looks_like_image_url(text):
            out.add(text)


def _load_library_index() -> LibraryIndex:
    if Config.TEST_MODE:
        client = LocalClient()
    else:
        client = SharePointListClient()

    records = client.get_all_records()
    filenames: set[str] = set()
    slugs: set[str] = set()
    locations: set[str] = set()

    for rec in records:
        fields = rec.get("fields", {}) if isinstance(rec, dict) else {}
        filename = str(fields.get("Filename", "") or "").strip().lower()
        if filename:
            filenames.add(filename)
        slug = str(fields.get("Slug", "") or "").strip().lower()
        if slug:
            slugs.add(slug)
        location = str(fields.get("Location", "") or "").strip().lower()
        if location:
            locations.add(location)

    return LibraryIndex(filenames=filenames, slugs=slugs, locations=locations)


def _webflow_get(url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {"value": data}


def _list_collections(api_base: str, site_id: str, headers: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    candidates = [
        (f"{api_base}/v2/sites/{site_id}/collections", "v2"),
        (f"{api_base}/sites/{site_id}/collections", "v1"),
    ]

    last_error: Exception | None = None
    for url, mode in candidates:
        try:
            data = _webflow_get(url, headers)
            if isinstance(data.get("collections"), list):
                return data["collections"], mode
            if isinstance(data.get("value"), list):
                return data["value"], mode
            if isinstance(data, list):
                return data, mode
            return [], mode
        except requests.exceptions.HTTPError as e:
            last_error = e
            continue

    if last_error is not None:
        raise last_error
    return [], "unknown"


def _list_collection_items(api_base: str, collection_id: str, headers: dict[str, str], mode: str) -> list[dict[str, Any]]:
    if mode == "v1":
        url = f"{api_base}/collections/{collection_id}/items"
    else:
        url = f"{api_base}/v2/collections/{collection_id}/items"
    items: list[dict[str, Any]] = []
    offset = 0
    limit = 100

    while True:
        data = _webflow_get(url, headers, params={"limit": limit, "offset": offset})
        page_items = data.get("items", [])
        if not isinstance(page_items, list):
            page_items = []
        items.extend(i for i in page_items if isinstance(i, dict))

        pagination = data.get("pagination", {}) if isinstance(data.get("pagination"), dict) else {}
        total = pagination.get("total")
        if isinstance(total, int):
            if len(items) >= total:
                break
        elif len(page_items) < limit:
            break

        offset += limit

    return items


def _match_library(url: str, index: LibraryIndex) -> tuple[bool, str, str]:
    parsed = urlparse(url)
    decoded_path = unquote(parsed.path or "")
    basename = Path(decoded_path).name.strip().lower()
    if not basename:
        return False, "", "no-basename"

    slug = Path(basename).stem.strip().lower()

    if basename in index.filenames:
        return True, basename, "filename"
    if slug in index.slugs:
        return True, basename, "slug"
    if decoded_path.lower().lstrip("/") in index.locations:
        return True, basename, "location"

    return False, basename, "none"


def main() -> int:
    token = os.getenv("WEBFLOW_API_TOKEN", "").strip()
    site_id = os.getenv("WEBFLOW_SITE_ID", "").strip()
    api_base = os.getenv("WEBFLOW_API_BASE", "https://api.webflow.com").rstrip("/")

    if not token:
        print("ERROR: WEBFLOW_API_TOKEN is required")
        return 2
    if not site_id:
        print("ERROR: WEBFLOW_SITE_ID is required")
        return 2

    print("Building library index...")
    index = _load_library_index()
    print(f"Library records indexed: filenames={len(index.filenames)}, slugs={len(index.slugs)}")

    headers = _webflow_headers(token)
    print("Fetching Webflow collections...")
    collections, mode = _list_collections(api_base, site_id, headers)
    print(f"Collections found: {len(collections)} (api mode: {mode})")

    usages: list[dict[str, Any]] = []
    matched = 0
    missing = 0

    for col in collections:
        col_id = str(col.get("id", "") or "").strip()
        col_name = str(col.get("displayName", "") or col.get("name", "") or col_id)
        if not col_id:
            continue

        items = _list_collection_items(api_base, col_id, headers, mode)
        print(f"- {col_name}: {len(items)} item(s)")

        for item in items:
            urls: set[str] = set()
            _extract_image_urls(item, urls)
            if not urls:
                continue

            item_id = str(item.get("id", "") or "")
            item_name = str(item.get("fieldData", {}).get("name", "") or item.get("name", "") or item_id)

            for url in sorted(urls):
                is_match, basename, match_rule = _match_library(url, index)
                usages.append(
                    {
                        "collection_id": col_id,
                        "collection_name": col_name,
                        "item_id": item_id,
                        "item_name": item_name,
                        "url": url,
                        "basename": basename,
                        "in_library": is_match,
                        "match_rule": match_rule,
                    }
                )
                if is_match:
                    matched += 1
                else:
                    missing += 1

    report = {
        "summary": {
            "collections_scanned": len(collections),
            "image_references_scanned": len(usages),
            "matched_in_library": matched,
            "missing_from_library": missing,
        },
        "missing": [u for u in usages if not u["in_library"]],
        "all": usages,
    }

    out_path = Path("test_data") / "cms_library_audit_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nAudit complete")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report written: {out_path}")

    if missing > 0:
        print("\nTop missing references:")
        for row in report["missing"][:20]:
            print(f"- [{row['collection_name']}] {row['item_name']} -> {row['url']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
