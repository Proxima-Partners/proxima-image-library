"""Tag vocabulary library — stored in SharePoint, cached in memory.

Tags starting with '?' are AI-suggested and pending human review.
Use the tag manager UI or API to promote or discard them.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from src.config import Config


_CACHE_TTL = 300        # seconds before re-fetching from SharePoint
_SP_FOLDER = "Config"   # folder in SharePoint drive root
_SP_FILE   = "tag_library.json"
_SP_PATH   = f"{_SP_FOLDER}/{_SP_FILE}"

# Seed vocabulary — used when no SharePoint file exists yet
_DEFAULT_TAGS: Dict[str, List[str]] = {
    "People": [
        "people", "headshot", "group", "individual", "staff", "volunteer",
        "family", "youth", "children", "elderly", "unhoused", "neighbor", "community",
    ],
    "Location — SF": [
        "city", "san-francisco", "bay-area", "golden-gate", "mission-district",
    ],
    "Location — type": [
        "landscape", "architecture", "street", "cafe", "office", "church",
        "indoor", "outdoor", "park", "beach", "mountains", "waterfront",
        "urban", "suburban", "rural", "forest", "plaza", "rooftop", "bridge",
        "neighborhood",
    ],
    "Emotion / theme": [
        "hope", "connection", "service", "prayer", "celebration",
        "hardship", "joy", "loneliness", "generosity",
    ],
    "Content type": [
        "icon", "logo", "illustration", "graphic", "vector",
        "document", "map", "badge", "partner",
    ],
    "Framing": [
        "portrait", "thumbnail", "banner", "background", "photo",
    ],
}


class TagLibrary:
    """Singleton that manages the predefined tag vocabulary.

    Loads from SharePoint on first access and caches for CACHE_TTL seconds.
    Falls back to _DEFAULT_TAGS if SharePoint is unavailable.
    """

    _instance: Optional["TagLibrary"] = None

    def __init__(self):
        self._data: Dict[str, List[str]] = {}
        self._loaded_at: float = 0.0
        self._sp = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_sp(self):
        if self._sp is None and Config.STORAGE_MODE == "sharepoint":
            from src.sharepoint_client import SharePointClient
            self._sp = SharePointClient()
        return self._sp

    def _local_path(self) -> Path:
        return Path(Config.TAG_LIBRARY_PATH).expanduser()

    def _load(self) -> None:
        sp = self._get_sp()
        if sp:
            try:
                content = sp.get_file_bytes(_SP_PATH)
                self._data = json.loads(content)
                self._loaded_at = time.time()
                return
            except Exception:
                pass  # Fall through to local file

        local = self._local_path()
        if local.exists():
            try:
                self._data = json.loads(local.read_text(encoding="utf-8"))
                self._loaded_at = time.time()
                return
            except Exception:
                pass  # Fall through to defaults

        self._data = {k: list(v) for k, v in _DEFAULT_TAGS.items()}
        self._loaded_at = time.time()

    def _ensure_loaded(self) -> None:
        if not self._data or time.time() - self._loaded_at > _CACHE_TTL:
            self._load()

    def _save(self) -> None:
        sp = self._get_sp()
        if sp:
            try:
                content = json.dumps(self._data, indent=2, ensure_ascii=False).encode("utf-8")
                sp.upload_file(_SP_FOLDER, _SP_FILE, content)
                return
            except Exception as e:
                print(f"Warning: could not save tag library to SharePoint: {e}")

        local = self._local_path()
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            print(f"Warning: could not save tag library to {local}: {e}")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_all(self) -> Dict[str, List[str]]:
        """Return {category: [tags]} — includes all tags."""
        self._ensure_loaded()
        return self._data

    def get_flat(self) -> List[str]:
        """Return a flat sorted list of all approved tags (no ? prefix)."""
        self._ensure_loaded()
        return sorted(
            tag for tags in self._data.values() for tag in tags
            if not tag.startswith("?")
        )

    def add_tag(self, tag: str, category: str = "Custom") -> None:
        """Add a tag (creates category if needed). Strips ? prefix."""
        self._ensure_loaded()
        tag = tag.lstrip("?").strip().lower()
        if not tag:
            return
        if category not in self._data:
            self._data[category] = []
        if tag not in self._data[category]:
            self._data[category].append(tag)
            self._save()

    def remove_tag(self, tag: str) -> bool:
        """Remove a tag from all categories. Returns True if found."""
        self._ensure_loaded()
        tag = tag.strip().lower()
        found = False
        for tags in self._data.values():
            if tag in tags:
                tags.remove(tag)
                found = True
        if found:
            self._save()
        return found

    def promote_suggestion(self, suggested_tag: str, category: str = "Custom") -> None:
        """Promote a ?suggested tag to an approved tag in the given category."""
        clean = suggested_tag.lstrip("?").strip().lower()
        self.add_tag(clean, category)

    def suggest_category(self, suggested_tag: str) -> str:
        """Return the best-matching category for a suggested tag using token overlap.

        Scoring is based on the best single approved-tag match within each category
        (not cumulative) to avoid categories with many short tags winning by volume.
        """
        self._ensure_loaded()
        clean = suggested_tag.lstrip("?").strip().lower()
        tokens = set(clean.replace("-", " ").replace("_", " ").split())
        if not tokens:
            return "Custom"

        best_category = "Custom"
        best_score = 0

        for category, approved_tags in self._data.items():
            category_best = 0
            for approved in approved_tags:
                approved_tokens = set(approved.replace("-", " ").replace("_", " ").split())
                # Exact match — return immediately
                if clean == approved:
                    return category
                # Token intersection (Jaccard-weighted)
                intersection = tokens & approved_tokens
                union = tokens | approved_tokens
                if not intersection:
                    continue
                # Jaccard similarity scaled to avoid penalising short tags
                score = len(intersection) / len(union)
                # Bonus only when there's already token overlap and one contains the other
                if clean in approved or approved in clean:
                    score += 0.25
                if score > category_best:
                    category_best = score
            if category_best > best_score:
                best_score = category_best
                best_category = category

        return best_category

    def invalidate_cache(self) -> None:
        """Force a reload from SharePoint on next access."""
        self._loaded_at = 0.0

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "TagLibrary":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
