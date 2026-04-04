"""MCP server — exposes Proxima Image Library tools to Claude.

Tools:
  search_image_library   — full-text search against the internal SharePoint List
  search_stock_photos    — search Pexels, Shutterstock, Unsplash, Pixabay concurrently
  catalog_stock_image    — download a stock image URL, run the full pipeline, store it

Run as a stdio MCP server:
  python -m src.mcp_server

Register in Claude Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "proxima-image-library": {
        "command": "python",
        "args": ["-m", "src.mcp_server"],
        "cwd": "/path/to/proxima-image-library"
      }
    }
  }
"""

import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from src.config import Config

server = Server("proxima-image-library")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_record(fields: dict, phrases: list[str]) -> int:
    """Return a match score: how many phrases have at least one token hit in alt_text or tags."""
    text = " ".join([
        fields.get("Alt Text", ""),
        fields.get("Tags", ""),
        fields.get("Filename", ""),
    ]).lower()
    score = 0
    for phrase in phrases:
        tokens = re.findall(r"[a-z0-9]+", phrase.lower())
        if any(tok in text for tok in tokens):
            score += 1
    return score


def _get_list_client():
    if Config.TEST_MODE:
        from src.local_client import LocalClient
        return LocalClient()
    from src.sharepoint_list_client import SharePointListClient
    return SharePointListClient()


def _webp_url(location: str) -> str:
    """Build a full URL for an image location.  In production this would be the
    SharePoint CDN URL; for now return the /image Flask route path for local mode."""
    if not location:
        return ""
    if Config.STORAGE_MODE == "sharepoint":
        return f"served-via-sharepoint:{location}"
    return f"http://localhost:5000/image?path={location}"


# ---------------------------------------------------------------------------
# Tool: search_image_library
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_image_library",
            description=(
                "Search the Proxima internal image library. "
                "Pass the Photo Suggestion phrases from a blog or article skill output. "
                "Returns ranked matches with alt text, tags, slug, and image URL. "
                "Always try this before searching stock photo libraries."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "phrases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "1–20 search phrases. Use the Photo Suggestion phrases "
                            "from the writing skill output verbatim."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default 8, max 20).",
                        "default": 8,
                    },
                },
                "required": ["phrases"],
            },
        ),
        types.Tool(
            name="search_stock_photos",
            description=(
                "Search stock photo libraries (Pexels, Shutterstock, Unsplash, Pixabay) "
                "concurrently. Use this only after presenting internal library results "
                "and the user has not selected one. "
                "Returns results grouped by phrase, each with per-library tabs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "phrases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1–20 search phrases from the Photo Suggestion field.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Results per phrase per library (default 6, max 12).",
                        "default": 6,
                    },
                    "pexels_orientation": {
                        "type": "string",
                        "enum": ["landscape", "portrait", "square"],
                        "description": "Optional: filter Pexels results by orientation.",
                    },
                    "shutterstock_orientation": {
                        "type": "string",
                        "enum": ["horizontal", "vertical"],
                        "description": "Optional: filter Shutterstock results by orientation.",
                    },
                    "unsplash_orientation": {
                        "type": "string",
                        "enum": ["landscape", "portrait", "squarish"],
                        "description": "Optional: filter Unsplash results by orientation.",
                    },
                },
                "required": ["phrases"],
            },
        ),
        types.Tool(
            name="catalog_stock_image",
            description=(
                "Download a stock photo by URL, transform it to WebP, generate AI alt text "
                "and tags, store it in SharePoint, and write the metadata record. "
                "Call this after the user selects a stock photo result. "
                "Returns the final slug, filename, alt_text, tags, and location."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "download_url": {
                        "type": "string",
                        "description": "Direct download URL of the highest-resolution image available.",
                    },
                    "original_filename": {
                        "type": "string",
                        "description": "Original filename including extension (used to derive type).",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["Headshots", "Community", "Locations", "Situations", "Graphics", "Banners"],
                        "description": "Storage category. Infer from image content if not specified by user.",
                    },
                },
                "required": ["download_url", "original_filename", "category"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    if name == "search_image_library":
        return await _search_image_library(arguments)
    if name == "search_stock_photos":
        return await _search_stock_photos(arguments)
    if name == "catalog_stock_image":
        return await _catalog_stock_image(arguments)
    raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _search_image_library(args: dict) -> list[types.TextContent]:
    phrases = args.get("phrases", [])
    limit = max(1, min(int(args.get("limit", 8)), 20))

    if not phrases:
        return [types.TextContent(type="text", text="[]")]

    client = _get_list_client()
    records = client.get_all_records()

    scored = []
    for rec in records:
        fields = rec.get("fields", {})
        score = _score_record(fields, phrases)
        if score > 0:
            location = fields.get("Location", "")
            scored.append({
                "score": score,
                "slug": fields.get("Slug", ""),
                "filename": fields.get("Filename", ""),
                "alt_text": fields.get("Alt Text", ""),
                "tags": fields.get("Tags", ""),
                "location": location,
                "webp_url": _webp_url(location),
                "category": location.split("/")[0] if "/" in location else "",
                "status": fields.get("Status", ""),
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    results = scored[:limit]

    if not results:
        return [types.TextContent(
            type="text",
            text=(
                "No matches found in the internal library for these phrases. "
                "Use search_stock_photos to search external libraries."
            ),
        )]

    import json
    return [types.TextContent(type="text", text=json.dumps(results, indent=2))]


async def _search_stock_photos(args: dict) -> list[types.TextContent]:
    import json
    from src.stock_client import (
        search_pexels, search_shutterstock, search_unsplash,
        search_pixabay, search_all_libraries,
    )
    import concurrent.futures

    phrases = args.get("phrases", [])[:20]
    limit = max(1, min(int(args.get("limit", 6)), 12))

    pexels_orientation = args.get("pexels_orientation")
    shutterstock_orientation = args.get("shutterstock_orientation")
    unsplash_orientation = args.get("unsplash_orientation")

    if not phrases:
        return [types.TextContent(type="text", text="{}")]

    # Build per-library search functions with optional orientation params
    def _pexels(phrase, lim):
        import os
        api_key = os.getenv("PEXELS_API_KEY", "")
        if not api_key:
            return {"results": [], "error": "PEXELS_API_KEY not configured"}
        try:
            import requests
            params = {"query": phrase, "per_page": lim}
            if pexels_orientation:
                params["orientation"] = pexels_orientation
            r = requests.get(
                "https://api.pexels.com/v1/search",
                params=params,
                headers={"Authorization": api_key},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            return {"results": [
                {
                    "thumb": p.get("src", {}).get("medium", ""),
                    "download_url": p.get("src", {}).get("original", ""),
                    "title": p.get("alt", "") or phrase,
                    "link": p.get("url", ""),
                    "source": "pexels",
                }
                for p in data.get("photos", [])
            ], "error": None}
        except Exception as e:
            return {"results": [], "error": str(e)}

    def _shutterstock(phrase, lim):
        import os, base64, requests
        cid = os.getenv("SHUTTERSTOCK_CLIENT_ID", "")
        csec = os.getenv("SHUTTERSTOCK_CLIENT_SECRET", "")
        if not cid or not csec:
            return {"results": [], "error": "Shutterstock credentials not configured"}
        try:
            credentials = base64.b64encode(f"{cid}:{csec}".encode()).decode()
            params = {
                "query": phrase,
                "per_page": lim,
                "image_type": "photo",
                "fields": "id,description,assets",
            }
            if shutterstock_orientation:
                params["orientation"] = shutterstock_orientation
            r = requests.get(
                "https://api.shutterstock.com/v2/images/search",
                params=params,
                headers={"Authorization": f"Basic {credentials}"},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            results = []
            for item in data.get("data", []):
                item_id = item.get("id", "")
                desc = item.get("description", "")
                assets = item.get("assets", {})
                thumb = (
                    assets.get("large_thumb", {}).get("url")
                    or assets.get("preview", {}).get("url", "")
                )
                # Shutterstock requires licensing; provide link to license page
                results.append({
                    "thumb": thumb,
                    "download_url": None,  # requires licensing via Shutterstock
                    "title": desc,
                    "link": f"https://www.shutterstock.com/image-photo/{item_id}",
                    "source": "shutterstock",
                    "id": item_id,
                })
            return {"results": results, "error": None}
        except Exception as e:
            return {"results": [], "error": str(e)}

    def _unsplash(phrase, lim):
        import os, requests
        key = os.getenv("UNSPLASH_ACCESS_KEY", "")
        if not key:
            return {"results": [], "error": "UNSPLASH_ACCESS_KEY not configured"}
        try:
            params = {"query": phrase, "per_page": lim}
            if unsplash_orientation:
                params["orientation"] = unsplash_orientation
            r = requests.get(
                "https://api.unsplash.com/search/photos",
                params=params,
                headers={"Authorization": f"Client-ID {key}"},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            results = []
            for item in data.get("results", []):
                user = item.get("user", {})
                utm = "?utm_source=proxima_image_library&utm_medium=referral"
                results.append({
                    "thumb": item.get("urls", {}).get("small", ""),
                    "download_url": item.get("urls", {}).get("full", ""),
                    "title": item.get("alt_description") or item.get("description") or "",
                    "link": item.get("links", {}).get("html", "") + utm,
                    "photographer": user.get("name", ""),
                    "photographer_url": user.get("links", {}).get("html", "") + utm,
                    "source": "unsplash",
                })
            return {"results": results, "error": None}
        except Exception as e:
            return {"results": [], "error": str(e)}

    def _pixabay(phrase, lim):
        import os, requests
        key = os.getenv("PIXABAY_API_KEY", "")
        if not key:
            return {"results": [], "error": "PIXABAY_API_KEY not configured"}
        try:
            r = requests.get(
                "https://pixabay.com/api/",
                params={
                    "key": key,
                    "q": phrase,
                    "image_type": "photo",
                    "per_page": lim,
                    "safesearch": "true",
                },
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            return {"results": [
                {
                    "thumb": item.get("webformatURL", ""),
                    "download_url": item.get("largeImageURL", ""),
                    "title": item.get("tags", ""),
                    "link": item.get("pageURL", ""),
                    "source": "pixabay",
                }
                for item in data.get("hits", [])
            ], "error": None}
        except Exception as e:
            return {"results": [], "error": str(e)}

    searchers = {
        "pexels": _pexels,
        "shutterstock": _shutterstock,
        "unsplash": _unsplash,
        "pixabay": _pixabay,
    }

    output = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(phrases) * 4, 16)) as executor:
        future_map = {}
        for phrase in phrases:
            for lib, fn in searchers.items():
                future_map[executor.submit(fn, phrase, limit)] = (phrase, lib)

        for future in concurrent.futures.as_completed(future_map, timeout=25):
            phrase, lib = future_map[future]
            if phrase not in output:
                output[phrase] = {}
            try:
                output[phrase][lib] = future.result()
            except Exception as e:
                output[phrase][lib] = {"results": [], "error": str(e)}

    return [types.TextContent(type="text", text=json.dumps(output, indent=2))]


async def _catalog_stock_image(args: dict) -> list[types.TextContent]:
    import json
    import requests as req

    download_url = args.get("download_url", "").strip()
    original_filename = args.get("original_filename", "image.jpg").strip()
    category = args.get("category", "")

    if not download_url:
        return [types.TextContent(type="text", text=json.dumps({"error": "download_url is required"}))]

    # Download the image
    try:
        resp = req.get(download_url, timeout=30)
        resp.raise_for_status()
        file_bytes = resp.content
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": f"Download failed: {e}"}))]

    # Run full pipeline
    from src.ai_generator import AltTextGenerator
    from src.image_processor import process_image

    gen = AltTextGenerator()

    if Config.TEST_MODE:
        from src.local_client import LocalClient
        list_client = LocalClient()
        sp_client = None
        storage_mode = "local"
    else:
        from src.sharepoint_list_client import SharePointListClient
        from src.sharepoint_client import SharePointClient
        list_client = SharePointListClient()
        sp_client = SharePointClient()
        storage_mode = "sharepoint"

    try:
        result = process_image(
            file_bytes=file_bytes,
            original_filename=original_filename,
            category=category,
            generator=gen,
            list_client=list_client,
            sp_client=sp_client,
            image_folder=Config.IMAGE_FOLDER,
            storage_mode=storage_mode,
        )
        result["webp_url"] = _webp_url(result.get("location", ""))
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
