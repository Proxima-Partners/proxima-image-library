"""Stock photo search clients for Pexels, Shutterstock, and Unsplash."""

import base64
import concurrent.futures
import os
import re

import requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text or "").lower().strip()
    s = re.sub(r"[\s-]+", "-", s)
    return s[:max_len].rstrip("-")


# ---------------------------------------------------------------------------
# Per-library search functions
# ---------------------------------------------------------------------------

def search_pexels(phrase: str, limit: int = 8) -> dict:
    """Search Pexels. Returns {results: [...], error: str|None}."""
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return {"results": [], "error": "PEXELS_API_KEY not configured"}
    try:
        headers = {"Authorization": api_key}
        params = {"query": phrase, "per_page": limit}
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params=params,
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        results = []
        for item in data.get("photos", []):
            title = item.get("alt", "") or phrase
            results.append({
                "thumb": item.get("src", {}).get("medium", ""),
                "title": title,
                "link": item.get("url", ""),
            })
        return {"results": results, "error": None}
    except requests.HTTPError as e:
        return {"results": [], "error": f"Pexels API error {e.response.status_code}"}
    except Exception as e:
        return {"results": [], "error": str(e)}


def search_shutterstock(phrase: str, limit: int = 8) -> dict:
    """Search Shutterstock. Returns {results: [...], error: str|None}."""
    client_id = os.getenv("SHUTTERSTOCK_CLIENT_ID", "")
    client_secret = os.getenv("SHUTTERSTOCK_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return {"results": [], "error": "SHUTTERSTOCK_CLIENT_ID / SHUTTERSTOCK_CLIENT_SECRET not configured"}
    try:
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}
        params = {
            "query": phrase,
            "per_page": limit,
            "image_type": "photo",
            "fields": "id,description,assets",
        }
        r = requests.get(
            "https://api.shutterstock.com/v2/images/search",
            params=params,
            headers=headers,
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
            results.append({
                "thumb": thumb,
                "title": desc,
                "link": f"https://www.shutterstock.com/image-photo/{_slug(desc) or 'photo'}-{item_id}",
            })
        return {"results": results, "error": None}
    except requests.HTTPError as e:
        return {"results": [], "error": f"Shutterstock API error {e.response.status_code}"}
    except Exception as e:
        return {"results": [], "error": str(e)}


def search_unsplash(phrase: str, limit: int = 8) -> dict:
    """Search Unsplash. Returns {results: [...], error: str|None}."""
    access_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
    if not access_key:
        return {"results": [], "error": "UNSPLASH_ACCESS_KEY not configured"}
    try:
        headers = {"Authorization": f"Client-ID {access_key}"}
        params = {"query": phrase, "per_page": limit}
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params=params,
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        results = []
        for item in data.get("results", []):
            user = item.get("user", {})
            photographer = user.get("name", "")
            profile_url = (
                user.get("links", {}).get("html", "")
                + "?utm_source=proxima_image_library&utm_medium=referral"
            )
            photo_link = (
                item.get("links", {}).get("html", "")
                + "?utm_source=proxima_image_library&utm_medium=referral"
            )
            results.append({
                "thumb": item.get("urls", {}).get("small", ""),
                "title": item.get("alt_description") or item.get("description") or "",
                "link": photo_link,
                "photographer": photographer,
                "photographer_url": profile_url,
            })
        return {"results": results, "error": None}
    except requests.HTTPError as e:
        return {"results": [], "error": f"Unsplash API error {e.response.status_code}"}
    except Exception as e:
        return {"results": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Concurrent multi-library search
# ---------------------------------------------------------------------------

def search_all_libraries(phrases: list, limit: int = 8) -> list:
    """Search all three libraries for all phrases concurrently."""
    searchers = {
        "pexels": search_pexels,
        "shutterstock": search_shutterstock,
        "unsplash": search_unsplash,
    }

    results_map = {p: {} for p in phrases}
    max_workers = min(len(phrases) * 3, 12)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_key = {}
        for phrase in phrases:
            for lib_name, fn in searchers.items():
                f = executor.submit(fn, phrase, limit)
                future_to_key[f] = (phrase, lib_name)

        for future in concurrent.futures.as_completed(future_to_key, timeout=25):
            phrase, lib_name = future_to_key[future]
            try:
                results_map[phrase][lib_name] = future.result()
            except Exception as e:
                results_map[phrase][lib_name] = {"results": [], "error": str(e)}

    return [{"phrase": p, **results_map[p]} for p in phrases]


# ---------------------------------------------------------------------------
# Phrase extractor
# ---------------------------------------------------------------------------

def parse_photo_suggestions(content: str) -> list:
    """
    Extract photo suggestion phrases from skill output content.

    Handles:
    - Full markdown skill output with a "Photo Suggestion" section
    - Plain text / one phrase per line
    """
    lines = content.splitlines()

    # ── Phase 1: find Photo Suggestion section ──────────────────────────
    in_section = False
    section_lines = []
    blank_run = 0

    for line in lines:
        if re.search(r"photo\s+suggestion", line, re.IGNORECASE):
            in_section = True
            continue

        if in_section:
            stripped = line.strip()
            # Stop at next numbered output field or markdown heading
            if stripped and re.match(r"^(#+\s|\d+\.\s+\*\*)", stripped):
                break
            if not stripped:
                blank_run += 1
                if blank_run >= 2:
                    break
            else:
                blank_run = 0
                section_lines.append(stripped)

    # ── Phase 2: clean and validate ──────────────────────────────────────
    def _clean(line: str) -> str:
        line = re.sub(r"^```.*$", "", line)                        # code fences
        line = re.sub(r"^[\-\*\+\s>`]+", "", line)                 # bullets
        line = re.sub(r"^\d+[.\)]\s*", "", line)                   # numbered list
        line = re.sub(r"\*{1,2}([^*]*)\*{1,2}", r"\1", line)       # bold/italic
        line = re.sub(r"`([^`]*)`", r"\1", line)                    # inline code
        return line.strip().strip("\"'")

    def _valid(phrase: str) -> bool:
        words = phrase.split()
        return (
            1 <= len(words) <= 7
            and not re.search(r"—{1,}", phrase)
            and not re.search(
                r"(suggestion|adobe|shutterstock|unsplash|search phrase|per the)",
                phrase,
                re.IGNORECASE,
            )
        )

    if section_lines:
        phrases = [_clean(ln) for ln in section_lines]
        phrases = [p for p in phrases if _valid(p)]
        if phrases:
            return phrases[:20]

    # ── Fallback: treat each non-empty line as a phrase ─────────────────
    phrases = [_clean(ln) for ln in lines if ln.strip()]
    return [p for p in phrases if _valid(p)][:20]
