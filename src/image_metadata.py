"""Sidecar metadata for additive image-delivery features.

The legacy SharePoint List schema remains unchanged. New ingestion writes one
JSON document per slug under Metadata/, which keeps current MCP/API consumers
working while allowing richer derivative, rights, and focal-point metadata.
"""

import json
import re
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Optional

from src.config import Config


_SIDECAR_CACHE: dict[str, tuple[float, set[str]]] = {}
_SIDECAR_CACHE_LOCK = threading.Lock()
_SIDECAR_CACHE_SECONDS = 60


def metadata_location(slug: str) -> str:
    safe_slug = str(slug or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", safe_slug):
        raise ValueError("A valid slug is required")
    return f"Metadata/{safe_slug}.json"


def write_metadata(
    metadata: dict,
    *,
    storage_mode: str,
    image_folder: str,
    sp_client=None,
) -> str:
    slug = str(metadata.get("slug", "")).strip()
    relative = metadata_location(slug)
    content = json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8")
    if storage_mode == "sharepoint" and sp_client is not None:
        root = (Config.SHAREPOINT_IMAGE_FOLDER or "").strip().strip("/")
        folder = f"{root}/Metadata" if root else "Metadata"
        sp_client.upload_file(folder, f"{slug}.json", content)
    else:
        path = Path(image_folder) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    with _SIDECAR_CACHE_LOCK:
        _SIDECAR_CACHE.clear()
    return relative


def metadata_exists(
    slug: str,
    *,
    storage_mode: Optional[str] = None,
    image_folder: Optional[str] = None,
    sp_client=None,
) -> bool:
    """Check sidecar availability with one cached folder listing in SharePoint."""
    safe_slug = str(slug or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", safe_slug):
        return False
    mode = storage_mode or Config.STORAGE_MODE
    folder = image_folder or Config.IMAGE_FOLDER
    if mode != "sharepoint":
        return (Path(folder) / metadata_location(safe_slug)).is_file()

    root = (Config.SHAREPOINT_IMAGE_FOLDER or "").strip().strip("/")
    cache_key = f"sharepoint:{root}"
    now = time.monotonic()
    with _SIDECAR_CACHE_LOCK:
        cached = _SIDECAR_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return safe_slug in cached[1]
    try:
        if sp_client is None:
            from src.sharepoint_client import SharePointClient
            sp_client = SharePointClient()
        metadata_folder = f"{root}/Metadata" if root else "Metadata"
        slugs = {
            PurePosixPath(item.get("name", "")).stem
            for item in sp_client.list_folder(metadata_folder)
            if item.get("name", "").lower().endswith(".json")
        }
    except Exception:
        slugs = set()
    with _SIDECAR_CACHE_LOCK:
        _SIDECAR_CACHE[cache_key] = (now + _SIDECAR_CACHE_SECONDS, slugs)
    return safe_slug in slugs


def read_metadata(
    slug: str,
    *,
    storage_mode: Optional[str] = None,
    image_folder: Optional[str] = None,
    sp_client=None,
) -> dict:
    mode = storage_mode or Config.STORAGE_MODE
    folder = image_folder or Config.IMAGE_FOLDER
    relative = metadata_location(slug)
    try:
        if not metadata_exists(
            slug,
            storage_mode=mode,
            image_folder=folder,
            sp_client=sp_client,
        ):
            return {}
        if mode == "sharepoint":
            if sp_client is None:
                from src.sharepoint_client import SharePointClient
                sp_client = SharePointClient()
            root = (Config.SHAREPOINT_IMAGE_FOLDER or "").strip().strip("/")
            path = f"{root}/{relative}" if root else relative
            raw = sp_client.get_file_bytes(path)
        else:
            raw = (Path(folder) / relative).read_bytes()
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    except Exception:
        # Missing sidecars are normal for the pre-upgrade catalog. Do not let
        # them make legacy search/API responses fail.
        return {}


def update_focal_point(
    slug: str,
    x: float,
    y: float,
    *,
    storage_mode: Optional[str] = None,
    image_folder: Optional[str] = None,
    sp_client=None,
) -> dict:
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ValueError("focal point x and y must each be between 0 and 1")
    mode = storage_mode or Config.STORAGE_MODE
    folder = image_folder or Config.IMAGE_FOLDER
    metadata = read_metadata(
        slug,
        storage_mode=mode,
        image_folder=folder,
        sp_client=sp_client,
    )
    if not metadata:
        raise FileNotFoundError(f"No metadata exists for slug '{slug}'")
    metadata["focalPoint"] = {"x": float(x), "y": float(y)}
    write_metadata(
        metadata,
        storage_mode=mode,
        image_folder=folder,
        sp_client=sp_client,
    )
    return metadata


# ---------------------------------------------------------------------------
# Rights / license metadata (top-level ``rights`` key in the sidecar)
#
# Never invent license data: blank or "unknown" means not known. A statement
# is not a verified record — verification.status stays "unverified" until the
# license evidence is attached and a reviewer is named.
# ---------------------------------------------------------------------------

LICENSE_TYPES = ("standard", "extended", "editorial", "free", "internal", "unknown")
RELEASE_VALUES = ("released", "not-required", "not-released", "unknown")
CHANNELS = ("web", "print", "social", "fundraising", "advertising")
VERIFICATION_STATUSES = ("unverified", "verified")
RIGHTS_STATUSES = ("verified", "unverified", "incomplete", "none")

_RIGHTS_STRING_FIELDS = (
    "assetId", "source", "providerAssetId", "contributor", "licenseType",
    "licenseReference", "licensedOn", "licensee", "modelRelease",
    "propertyRelease", "releaseLocation", "expiration",
)
_RIGHTS_LIST_FIELDS = ("approvedChannels", "restrictions", "approvedCrops")
_RIGHTS_FIELDS = _RIGHTS_STRING_FIELDS + _RIGHTS_LIST_FIELDS + ("statements", "verification")
_VERIFICATION_FIELDS = ("status", "verifiedBy", "verifiedOn", "evidence")

STOCK_SOURCES = ("AdobeStock", "ShutterStock")
FREE_SOURCES = ("Pexels", "Pixabay", "Unsplash")
REQUIRED_RIGHTS_FIELDS = {
    "stock": (
        "providerAssetId", "contributor", "licenseType", "licenseReference",
        "licensedOn", "modelRelease", "approvedChannels", "expiration",
    ),
    "free": ("contributor", "licenseType"),
    "Internal": ("licenseType", "modelRelease", "approvedChannels"),
}
# Licensed stock cannot be cataloged without these unless explicitly overridden.
HOLD_RIGHTS_FIELDS = ("licenseType", "licenseReference")

_SOURCE_LABELS = {
    "AdobeStock": "Adobe Stock",
    "ShutterStock": "Shutterstock",
    "Internal": "Internal",
}

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _is_iso_date(value: str) -> bool:
    if not _ISO_DATE.fullmatch(value):
        return False
    from datetime import date
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _known(value) -> bool:
    if isinstance(value, list):
        return bool(value)
    return bool(str(value or "").strip()) and str(value).strip().lower() != "unknown"


def validate_rights(rights: dict) -> dict:
    """Validate a (possibly partial) rights object and return a clean copy.

    Blank values are allowed and mean "not known". Raises ValueError on
    unknown keys, bad enum values, malformed dates, or malformed lists.
    """
    if not isinstance(rights, dict):
        raise ValueError("rights must be an object")
    unknown = sorted(set(rights) - set(_RIGHTS_FIELDS))
    if unknown:
        raise ValueError(f"Unknown rights field(s): {', '.join(unknown)}")

    clean: dict = {}
    for key in _RIGHTS_STRING_FIELDS:
        if key not in rights or rights[key] is None:
            continue
        if not isinstance(rights[key], str):
            raise ValueError(f"rights.{key} must be a string")
        clean[key] = rights[key].strip()

    def _enum(key: str, allowed: tuple) -> None:
        value = clean.get(key, "")
        if value and value not in allowed:
            raise ValueError(f"rights.{key} must be one of: {', '.join(allowed)}")

    _enum("licenseType", LICENSE_TYPES)
    _enum("modelRelease", RELEASE_VALUES)
    _enum("propertyRelease", RELEASE_VALUES)
    if clean.get("source"):
        from src.image_processor import SOURCES
        if clean["source"] not in SOURCES:
            raise ValueError(f"rights.source must be one of: {', '.join(SOURCES)}")
    if clean.get("licensedOn") and not _is_iso_date(clean["licensedOn"]):
        raise ValueError("rights.licensedOn must be a YYYY-MM-DD date")
    expiration = clean.get("expiration", "")
    if expiration and expiration not in ("perpetual", "unknown") and not _is_iso_date(expiration):
        raise ValueError("rights.expiration must be YYYY-MM-DD, 'perpetual', or 'unknown'")

    for key in _RIGHTS_LIST_FIELDS:
        if key not in rights or rights[key] is None:
            continue
        value = rights[key]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"rights.{key} must be a list of strings")
        clean[key] = list(dict.fromkeys(v.strip() for v in value if v.strip()))
    bad_channels = sorted(set(clean.get("approvedChannels", [])) - set(CHANNELS))
    if bad_channels:
        raise ValueError(
            f"Unknown approved channel(s): {', '.join(bad_channels)}. "
            f"Allowed: {', '.join(CHANNELS)}"
        )

    if rights.get("statements") is not None:
        statements = rights["statements"]
        if not isinstance(statements, list):
            raise ValueError("rights.statements must be a list")
        clean["statements"] = []
        for item in statements:
            if not isinstance(item, dict):
                raise ValueError("Each statement must be an object with by, on, text")
            entry = {k: str(item.get(k, "") or "").strip() for k in ("by", "on", "text")}
            if not all(entry.values()):
                raise ValueError("Each statement requires by, on, and text")
            if not _is_iso_date(entry["on"]):
                raise ValueError("statement.on must be a YYYY-MM-DD date")
            clean["statements"].append(entry)

    if rights.get("verification") is not None:
        verification = rights["verification"]
        if not isinstance(verification, dict):
            raise ValueError("rights.verification must be an object")
        extra = sorted(set(verification) - set(_VERIFICATION_FIELDS))
        if extra:
            raise ValueError(f"Unknown verification field(s): {', '.join(extra)}")
        clean_v = {k: str(verification.get(k, "") or "").strip() for k in _VERIFICATION_FIELDS if k in verification}
        if clean_v.get("status") and clean_v["status"] not in VERIFICATION_STATUSES:
            raise ValueError("verification.status must be 'unverified' or 'verified'")
        if clean_v.get("verifiedOn") and not _is_iso_date(clean_v["verifiedOn"]):
            raise ValueError("verification.verifiedOn must be a YYYY-MM-DD date")
        clean["verification"] = clean_v
    return clean


def _check_verification(rights: dict) -> None:
    verification = rights.get("verification") or {}
    if verification.get("status") == "verified":
        missing = [k for k in ("evidence", "verifiedBy", "verifiedOn") if not verification.get(k)]
        if missing:
            raise ValueError(
                "verification.status 'verified' requires evidence, verifiedBy and verifiedOn "
                f"(missing: {', '.join(missing)})"
            )


def finalize_rights(rights: dict, *, slug: str, source: str) -> dict:
    """Apply defaults (assetId, source, unverified status) and the verification rule."""
    result = dict(rights)
    result.setdefault("assetId", "")
    result["assetId"] = result["assetId"] or slug
    result["source"] = result.get("source") or source
    verification = dict(result.get("verification") or {})
    verification["status"] = verification.get("status") or "unverified"
    result["verification"] = verification
    _check_verification(result)
    return result


def merge_rights(existing: dict, patch: dict, *, force: bool = False) -> tuple[dict, list[str]]:
    """Merge a validated patch into existing rights.

    - Blank patch values never erase existing values.
    - A different non-empty value only replaces an existing one with force=True;
      otherwise the field is reported in the returned conflict list.
    - Statements are append-only (deduplicated).
    - verification.status may move unverified → verified without force.
    """
    merged = dict(existing or {})
    conflicts: list[str] = []

    def _apply(target: dict, key: str, new, label: str) -> None:
        old = target.get(key)
        if not _has_value(new) or new == old:
            return
        if _has_value(old) and not force:
            conflicts.append(label)
            return
        target[key] = new

    for key in _RIGHTS_STRING_FIELDS + _RIGHTS_LIST_FIELDS:
        if key in patch:
            _apply(merged, key, patch[key], key)

    if patch.get("statements"):
        statements = list(merged.get("statements") or [])
        for item in patch["statements"]:
            if item not in statements:
                statements.append(item)
        merged["statements"] = statements

    if "verification" in patch:
        verification = dict(merged.get("verification") or {})
        new_v = patch["verification"]
        for key in ("verifiedBy", "verifiedOn", "evidence"):
            if key in new_v:
                _apply(verification, key, new_v[key], f"verification.{key}")
        new_status = new_v.get("status", "")
        old_status = verification.get("status", "")
        if new_status and new_status != old_status:
            if old_status in ("", "unverified") or force:
                verification["status"] = new_status
            else:
                conflicts.append("verification.status")
        merged["verification"] = verification
    return merged, conflicts


def _has_value(value) -> bool:
    if isinstance(value, list):
        return bool(value)
    return bool(str(value or "").strip())


def _source_group(source: str) -> str:
    if source in STOCK_SOURCES:
        return "stock"
    if source in FREE_SOURCES:
        return "free"
    return "Internal"


def rights_source(metadata: dict) -> str:
    rights = metadata.get("rights") if isinstance(metadata.get("rights"), dict) else {}
    original = metadata.get("original") if isinstance(metadata.get("original"), dict) else {}
    return str(rights.get("source") or original.get("provider") or "")


def rights_missing(rights: Optional[dict], source: str) -> list[str]:
    """Required RIGHTS.md fields that are blank or 'unknown' for this source."""
    rights = rights or {}
    missing = [
        key for key in REQUIRED_RIGHTS_FIELDS[_source_group(source)]
        if not _known(rights.get(key))
    ]
    if (rights.get("verification") or {}).get("status") != "verified":
        missing.append("verification")
    return missing


def rights_status(rights: Optional[dict], source: str) -> str:
    if not rights:
        return "none"
    if (rights.get("verification") or {}).get("status") == "verified":
        return "verified"
    missing = [m for m in rights_missing(rights, source) if m != "verification"]
    return "incomplete" if missing else "unverified"


def rights_hold_missing(rights: Optional[dict], source: str) -> list[str]:
    """Fields that must be present before licensed stock may be cataloged."""
    if source not in STOCK_SOURCES:
        return []
    rights = rights or {}
    return [key for key in HOLD_RIGHTS_FIELDS if not _known(rights.get(key))]


def rights_summary(rights: Optional[dict]) -> Optional[dict]:
    if not rights:
        return None
    return {
        "licenseType": rights.get("licenseType", "") or "unknown",
        "verificationStatus": (rights.get("verification") or {}).get("status", "") or "unverified",
        "expiration": rights.get("expiration", "") or "unknown",
    }


def license_summary(rights: dict) -> str:
    """One-line human summary kept in original.license for legacy readers."""
    source = rights.get("source", "")
    label = _SOURCE_LABELS.get(source, source) or "Unknown source"
    status = (rights.get("verification") or {}).get("status", "") or "unverified"
    license_type = rights.get("licenseType", "")
    if not _known(license_type):
        return f"{label}: license details not yet recorded ({status})"
    text = f"{label} {license_type} license"
    if rights.get("licenseReference"):
        text += f", ref {rights['licenseReference']}"
    return f"{text} ({status})"


def read_rights(
    slug: str,
    *,
    storage_mode: Optional[str] = None,
    image_folder: Optional[str] = None,
    sp_client=None,
) -> Optional[dict]:
    """Return {slug, source, rights, missing, status}, or None if no sidecar."""
    metadata = read_metadata(slug, storage_mode=storage_mode, image_folder=image_folder, sp_client=sp_client)
    if not metadata:
        return None
    return describe_rights(metadata)


def describe_rights(metadata: dict) -> dict:
    rights = metadata.get("rights") if isinstance(metadata.get("rights"), dict) else {}
    source = rights_source(metadata)
    return {
        "slug": metadata.get("slug", ""),
        "source": source,
        "filename": (metadata.get("original") or {}).get("filename", ""),
        "rights": rights,
        "missing": rights_missing(rights, source),
        "status": rights_status(rights, source),
    }


def write_rights(
    slug: str,
    patch: dict,
    *,
    force: bool = False,
    storage_mode: Optional[str] = None,
    image_folder: Optional[str] = None,
    sp_client=None,
    dry_run: bool = False,
) -> dict:
    """Read-modify-write the sidecar's rights object.

    Returns describe_rights(...) plus ``conflicts`` (fields not overwritten
    because they already held a different value and force was not set).
    """
    clean = validate_rights(patch)
    mode = storage_mode or Config.STORAGE_MODE
    folder = image_folder or Config.IMAGE_FOLDER
    metadata = read_metadata(slug, storage_mode=mode, image_folder=folder, sp_client=sp_client)
    if not metadata:
        raise FileNotFoundError(f"No metadata exists for slug '{slug}'")
    merged, conflicts = merge_rights(metadata.get("rights") or {}, clean, force=force)
    original = metadata.get("original") if isinstance(metadata.get("original"), dict) else {}
    merged = finalize_rights(merged, slug=slug, source=rights_source({"rights": merged, "original": original}) or "Internal")
    metadata["rights"] = merged
    if original and (_known(merged.get("licenseType")) or not original.get("license")):
        original = dict(original)
        original["license"] = license_summary(merged)
        metadata["original"] = original
    if not dry_run:
        write_metadata(metadata, storage_mode=mode, image_folder=folder, sp_client=sp_client)
    result = describe_rights(metadata)
    result["conflicts"] = conflicts
    return result
