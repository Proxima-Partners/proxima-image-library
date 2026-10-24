"""Bounded, report-only Graph diagnostics. Never imports the Flask application.

No mutation API; credentials go only to configured Graph collections. This does
not prove read-only Entra permissions: a scoped identity is an activation gate.
"""
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
import json
import time
from urllib.parse import quote, unquote, urlsplit
import uuid

from PIL import Image
import requests

from src.maintenance_helpers import build_integrity_scorecard, sanitize_relative_path
from src.sharepoint_list_client import SharePointListClient

GRAPH = "https://graph.microsoft.com/v1.0"
IMAGE_SUFFIXES = {"jpg", "jpeg", "png", "gif", "webp"}


class DiagnosticStop(Exception):
    """Only static reason codes are reported, never provider exceptions."""
    def __init__(self, reason, *, failed=False):
        self.reason, self.failed = reason, failed
        super().__init__(reason)


@dataclass(frozen=True)
class Limits:
    seconds: int = 300
    records: int = 1000
    pages: int = 40
    requests: int = 120
    files: int = 3000
    folders: int = 100
    thumbnails: int = 20
    response_bytes: int = 2 * 1024 * 1024
    total_bytes: int = 20 * 1024 * 1024

    def __post_init__(self):
        maximums = dict(seconds=300, records=1000, pages=40, requests=120,
                        files=3000, folders=100, thumbnails=20,
                        response_bytes=2 * 1024 * 1024, total_bytes=20 * 1024 * 1024)
        for key, value in asdict(self).items():
            if type(value) is not int or not (0 if key == "thumbnails" else 1) <= value <= maximums[key]:
                raise ValueError("Diagnostic limits exceed reviewed bounds")


class Budget:
    def __init__(self, limits, clock=time.monotonic):
        self.limits, self.clock = limits, clock
        self.started = clock()
        self.requests = self.pages = self.bytes = 0

    def remaining(self):
        left = self.limits.seconds - (self.clock() - self.started)
        if left <= 0:
            raise DiagnosticStop("time_limit")
        return left

    def request(self):
        self.remaining()
        if self.requests >= self.limits.requests:
            raise DiagnosticStop("request_limit")
        self.requests += 1

    def page(self):
        self.remaining()
        if self.pages >= self.limits.pages:
            raise DiagnosticStop("page_limit")
        self.pages += 1


def component(value):
    if (not isinstance(value, str) or not value or value in {".", ".."} or len(value) > 300
            or any(c in value for c in "/\\\r\n?#%")):
        raise ValueError("Invalid diagnostic resource identifier")
    return quote(value, safe="")


class ReadOnlyGraph:
    def __init__(self, token, site, list_name, drive, budget, session=None):
        if not token or "\n" in token or "\r" in token:
            raise ValueError("A scoped diagnostic token is required")
        self.budget, self.token = budget, token
        self.list_url = f"{GRAPH}/sites/{component(site)}/lists/{component(list_name)}/items"
        self.drive_url = f"{GRAPH}/drives/{component(drive)}"
        self.session = session or requests.Session()
        self.session.trust_env = False  # no .netrc/proxy credentials

    def _graph_url(self, url):
        return (isinstance(url, str) and len(url) <= 8192
                and not any(c in url for c in "\r\n\\")
                and ".." not in unquote(urlsplit(url).path).split("/")
                and (url == self.list_url or url.startswith(self.list_url + "?")
                     or url.startswith(self.drive_url + "/"))
                and not urlsplit(url).fragment)

    def _media_url(self, url):
        try:
            parts = urlsplit(url)
            host = parts.hostname or ""
            return (len(url) <= 8192 and parts.scheme == "https" and parts.port in (None, 443)
                    and not parts.username and not parts.password and not parts.fragment
                    and any(host.endswith(suffix) for suffix in (".sharepoint.com", ".svc.ms", ".files.1drv.com")))
        except (TypeError, ValueError):
            return False

    def _get(self, url, *, media=False, redirect=False):
        if not (self._media_url(url) if media else self._graph_url(url)):
            raise DiagnosticStop("unsafe_read_url", failed=True)
        self.budget.request()
        headers = {"Accept": "image/*" if redirect or media else "application/json"}
        if not media:
            headers["Authorization"] = "Bearer " + self.token
        try:
            self.session.cookies.clear()
            with self.session.get(url, headers=headers, stream=True, allow_redirects=False,
                                  timeout=min(15, self.budget.remaining())) as response:
                if redirect and response.status_code == 302:
                    target = response.headers.get("Location", "")
                    response.close()
                    return self._get(target, media=True)
                if response.status_code == 404:
                    return None
                if response.status_code in (401, 403):
                    raise DiagnosticStop("authentication_denied", failed=True)
                if response.status_code == 429:
                    raise DiagnosticStop("provider_throttled")
                if response.status_code != 200:
                    raise DiagnosticStop("provider_read_failed", failed=True)
                raw = bytearray()
                for chunk in response.iter_content(65536):
                    self.budget.remaining()
                    self.budget.bytes += len(chunk)
                    if self.budget.bytes > self.budget.limits.total_bytes:
                        raise DiagnosticStop("byte_limit")
                    if len(raw) + len(chunk) > self.budget.limits.response_bytes:
                        raise DiagnosticStop("response_size_limit")
                    raw.extend(chunk)
                self.budget.remaining()
                return bytes(raw)
        except requests.RequestException:
            raise DiagnosticStop("provider_read_failed", failed=True) from None

    def pages(self, url, *, item_limit=None):
        seen, count = set(), 0
        while url:
            # Stop before requesting a page that could exceed the record cap.
            # This can conservatively leave a partial last page unread.
            if item_limit is not None and item_limit - count < min(100, item_limit):
                raise DiagnosticStop("record_limit")
            if url in seen:
                raise DiagnosticStop("pagination_cycle", failed=True)
            seen.add(url)
            self.budget.page()
            raw = self._get(url)
            if raw is None:
                raise DiagnosticStop("collection_not_found", failed=True)
            try:
                data = json.loads(raw)
                values, following = data["value"], data.get("@odata.nextLink")
                if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
                    raise ValueError()
                if following is not None and not isinstance(following, str):
                    raise ValueError()
                if following and urlsplit(following).path != urlsplit(url).path:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise DiagnosticStop("invalid_provider_response", failed=True) from None
            count += len(values)
            if item_limit is not None and count > item_limit:
                raise DiagnosticStop("record_limit")
            yield values
            url = following

    def records(self):
        limit = self.budget.limits.records
        for page in self.pages(self.list_url + f"?$expand=fields&$top={min(100, limit)}", item_limit=limit):
            for item in page:
                if not isinstance(item.get("fields"), dict) or not isinstance(item.get("id"), str):
                    raise DiagnosticStop("invalid_catalog_record", failed=True)
                fields = {app: item["fields"].get(sp) or "" for sp, app in SharePointListClient._TO_APP.items()}
                if any(not isinstance(value, str) for value in fields.values()):
                    raise DiagnosticStop("invalid_catalog_record", failed=True)
                yield {"id": item["id"], "fields": fields}

    def inventory(self, root, kind):
        path = sanitize_relative_path(root)
        if not path or "\\" in path or ":" in path or kind not in {"WebP", "High-Res"}:
            raise DiagnosticStop("invalid_root", failed=True)
        first = f"{self.drive_url}/root:/{quote(path, safe='/')}/{kind}:/children?$top=100"
        queue, folders, seen = deque([(first, "")]), 1, set()
        while queue:
            url, prefix = queue.popleft()
            for page in self.pages(url):
                for item in page:
                    self.budget.remaining()
                    name, identity = item.get("name"), item.get("id")
                    if (not isinstance(name, str) or not name or name in (".", "..")
                            or any(c in name for c in "/\\") or not isinstance(identity, str) or not identity):
                        raise DiagnosticStop("invalid_drive_item", failed=True)
                    if identity in seen:
                        raise DiagnosticStop("duplicate_drive_item", failed=True)
                    seen.add(identity)
                    relative = prefix + name
                    if "folder" in item:
                        folders += 1
                        if folders > self.budget.limits.folders:
                            raise DiagnosticStop("folder_limit")
                        queue.append((f"{self.drive_url}/items/{component(identity)}/children?$top=100", relative + "/"))
                    elif "file" in item and name.rsplit(".", 1)[-1].lower() in IMAGE_SUFFIXES:
                        yield relative, identity

    def thumbnail(self, identity):
        raw = self._get(f"{self.drive_url}/items/{component(identity)}/thumbnails/0/small/content", redirect=True)
        if raw is None:
            return "missing"
        try:
            with Image.open(BytesIO(raw)) as img:
                if img.width * img.height > 2_000_000:
                    return "invalid"
                img.verify()
            self.budget.remaining()
            return "ok"
        except (OSError, ValueError, Image.DecompressionBombError):
            return "invalid"


def scan(client, root, budget):
    """Counts are observational, not an atomic snapshot or a repair/deletion plan."""
    report = {"schema": 1, "run_id": uuid.uuid4().hex,
              "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "complete", "reasons": [], "limits": asdict(budget.limits),
              "catalog": {"complete": False, "records": 0},
              "inventory": {"complete": False, "files": 0},
              "references": {"status": "unknown", "missing_webp": None, "missing_original": None,
                             "orphan_webp": None, "orphan_original": None},
              "thumbnails": {"scope": "sample", "requested": budget.limits.thumbnails, "checked": 0,
                             "ok": 0, "missing": 0, "invalid": 0},
              "not_assessed": ["near_duplicates", "rights_semantics", "full_thumbnail_coverage"]}
    records, ids, inventory = [], set(), {"WebP": {}, "High-Res": {}}
    try:
        for record in client.records():
            budget.remaining()
            if len(records) >= budget.limits.records:
                raise DiagnosticStop("record_limit")
            if record["id"] in ids:
                raise DiagnosticStop("duplicate_catalog_record", failed=True)
            ids.add(record["id"])
            records.append(record)
            report["catalog"]["records"] = len(records)
        report["catalog"]["complete"] = True
        score = build_integrity_scorecard(records)
        keys = ("missing_alt", "missing_tags", "missing_slug", "missing_location", "missing_high_res_location", "missing_source")
        report["catalog"]["metadata_missing"] = {key: sum(row[key] for row in score["categories"]) for key in keys}
        report["catalog"]["unknown_status_count"] = score["unknown_status_count"]
        for kind in inventory:
            for path, identity in client.inventory(root, kind):
                budget.remaining()
                if report["inventory"]["files"] >= budget.limits.files:
                    raise DiagnosticStop("file_limit")
                if path in inventory[kind]:
                    raise DiagnosticStop("duplicate_inventory_path", failed=True)
                inventory[kind][path] = identity
                report["inventory"]["files"] += 1
        report["inventory"]["complete"] = True
        refs, missing = {"WebP": set(), "High-Res": set()}, Counter()
        for record in records:
            budget.remaining()
            for kind, field in (("WebP", "Location"), ("High-Res", "High-Res Location")):
                location = sanitize_relative_path(record["fields"].get(field, ""))
                if location:
                    refs[kind].add(location)
                if not location or location not in inventory[kind]:
                    missing[kind] += 1
        report["references"].update(status="observed", missing_webp=missing["WebP"],
            missing_original=missing["High-Res"], orphan_webp=len(set(inventory["WebP"]) - refs["WebP"]),
            orphan_original=len(set(inventory["High-Res"]) - refs["High-Res"]))
        candidates = sorted(refs["WebP"] & inventory["WebP"].keys())[:budget.limits.thumbnails]
        report["thumbnails"]["selected"] = len(candidates)
        for path in candidates:
            budget.remaining()
            result = client.thumbnail(inventory["WebP"][path])
            if result not in {"ok", "missing", "invalid"}:
                raise DiagnosticStop("invalid_thumbnail_result", failed=True)
            report["thumbnails"][result] += 1
            report["thumbnails"]["checked"] += 1
        budget.remaining()
    except DiagnosticStop as exc:
        report["status"] = "failed" if exc.failed else "incomplete"
        report["reasons"].append(exc.reason)
    except Exception:
        report["status"] = "failed"
        report["reasons"].append("diagnostic_error")
    report["usage"] = {"requests": budget.requests, "pages": budget.pages, "bytes": budget.bytes,
                       "elapsed_seconds": round(max(0, budget.clock() - budget.started), 3)}
    return report
