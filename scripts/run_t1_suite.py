#!/usr/bin/env python3
"""Automated T1 regression suite.

This script runs the repeatable, non-interactive portion of T1 against an
isolated local dataset so it can be re-run on future changes and in CI.

What it covers:
- Core API health and smoke checks in TEST_MODE/local
- Review workflow status transitions and batch approve behavior
- Thumbnail integrity checks
- Maintenance endpoint smoke checks
- UI static checks for badge refresh, approve-all wiring, nested folder filter
  logic, and load-more pagination wiring
- Auth-gate behavior in DEV_AUTH_BYPASS=false mode (non-interactive)

What it intentionally does NOT cover (manual/environment-dependent):
- Real MSAL valid/invalid user browser sign-in
- Real token expiry behavior after issued token expiration window
- Live Azure/SharePoint production tenant validation
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_TABLE_PATH = REPO_ROOT / "test_data" / "local_table.json"
DEFAULT_REPORT_PATH = REPO_ROOT / "test_data" / "t1_last_report.json"


@dataclass
class CheckResult:
    check_id: str
    ok: bool
    details: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.check_id,
            "ok": self.ok,
            "details": self.details,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _python_bin() -> str:
    venv_py = REPO_ROOT / ".venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _make_webp(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (640, 420)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color)
    img.save(path, format="WEBP", quality=80)


def _seed_dataset(image_root: Path) -> List[Dict[str, Any]]:
    """Create a deterministic local dataset for T1 automated checks."""
    records: List[Dict[str, Any]] = []

    fixture_rows = [
        {
            "id": "loc_t1_0001",
            "filename": "proxima-sf-bridge.webp",
            "alt": "Golden Gate Bridge and San Francisco skyline at sunset.",
            "tags": "san-francisco,bridge,city,landscape",
            "status": "approved",
            "slug": "golden-gate-bridge-and-san-francisco-skyline-at-sunset",
            "location": "photography/SanFrancisco_Images/proxima-sf-bridge.webp",
            "high_res": "Internal/proxima-sf-bridge-original.jpg",
            "source": "Internal",
            "color": (210, 90, 70),
        },
        {
            "id": "loc_t1_0002",
            "filename": "proxima-logo-partner.webp",
            "alt": "Proxima partner logo mark on white background.",
            "tags": "logo,brand,graphic",
            "status": "approved",
            "slug": "proxima-partner-logo-mark-on-white-background",
            "location": "logos/partners/proxima-logo-partner.webp",
            "high_res": "Internal/proxima-logo-partner-original.jpg",
            "source": "Internal",
            "color": (80, 140, 200),
        },
        {
            "id": "loc_t1_0003",
            "filename": "proxima-neighbors.webp",
            "alt": "Neighbors sharing coffee in a San Francisco neighborhood.",
            "tags": "people,community,san-francisco,neighborhood",
            "status": "pending-review",
            "slug": "neighbors-sharing-coffee-in-a-san-francisco-neighborhood",
            "location": "photography/people/proxima-neighbors.webp",
            "high_res": "Internal/proxima-neighbors-original.jpg",
            "source": "Internal",
            "color": (70, 160, 120),
        },
        {
            "id": "loc_t1_0004",
            "filename": "proxima-volunteer.webp",
            "alt": "Volunteer serving a community meal at an outdoor event.",
            "tags": "people,service,community",
            "status": "pending-review",
            "slug": "volunteer-serving-a-community-meal-at-an-outdoor-event",
            "location": "photography/people/proxima-volunteer.webp",
            "high_res": "Internal/proxima-volunteer-original.jpg",
            "source": "Internal",
            "color": (130, 160, 70),
        },
        {
            "id": "loc_t1_0005",
            "filename": "proxima-golden-gate-family.webp",
            "alt": "Family smiling near the Golden Gate Bridge overlook.",
            "tags": "people,golden-gate,san-francisco,joy",
            "status": "pending-review",
            "slug": "family-smiling-near-the-golden-gate-bridge-overlook",
            "location": "photography/SanFrancisco_Images/proxima-golden-gate-family.webp",
            "high_res": "Internal/proxima-golden-gate-family-original.jpg",
            "source": "Internal",
            "color": (190, 120, 70),
        },
        {
            "id": "loc_t1_0006",
            "filename": "proxima-archive.webp",
            "alt": "Archived concept graphic for historical campaign.",
            "tags": "graphic,archive,brand",
            "status": "archived",
            "slug": "archived-concept-graphic-for-historical-campaign",
            "location": "graphics/archive/proxima-archive.webp",
            "high_res": "Internal/proxima-archive-original.jpg",
            "source": "Internal",
            "color": (120, 110, 150),
        },
    ]

    for row in fixture_rows:
        webp_path = image_root / "WebP" / row["location"]
        _make_webp(webp_path, row["color"])
        records.append(
            {
                "id": row["id"],
                "fields": {
                    "Filename": row["filename"],
                    "Alt Text": row["alt"],
                    "Tags": row["tags"],
                    "Status": row["status"],
                    "Slug": row["slug"],
                    "Location": row["location"],
                    "High-Res Location": row["high_res"],
                    "Source": row["source"],
                },
            }
        )

    return records


def _wait_for_health(base_url: str, timeout_seconds: float = 25.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _start_server(port: int, image_root: Path, bypass_auth: bool) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "TEST_MODE": "true",
            "STORAGE_MODE": "local",
            "DEV_AUTH_BYPASS": "true" if bypass_auth else "false",
            "IMAGE_FOLDER": str(image_root),
            "FLASK_SECRET_KEY": "t1-automation-secret-key-0123456789abcdef",
            # Dummy MSAL values are enough for redirect-path checks.
            "MSAL_CLIENT_ID": "t1-dummy-client-id",
            "MSAL_CLIENT_SECRET": "t1-dummy-secret",
            "MSAL_TENANT_ID": "t1-dummy-tenant",
            "MSAL_REDIRECT_URI": f"http://localhost:{port}/auth/callback",
            "PYTHONUNBUFFERED": "1",
        }
    )

    cmd = [
        _python_bin(),
        "-m",
        "flask",
        "--app",
        "src.app",
        "run",
        "--port",
        str(port),
    ]

    return subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_server(proc: subprocess.Popen) -> str:
    output = ""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    if proc.stdout:
        try:
            output = proc.stdout.read()[-6000:]
        except Exception:
            output = ""
    return output


def _check_health(base_url: str) -> CheckResult:
    details: Dict[str, Any] = {}
    ok = True
    for path in ("/health", "/healthz"):
        try:
            resp = requests.get(f"{base_url}{path}", timeout=6)
            details[path] = resp.status_code
            ok = ok and (resp.status_code == 200)
        except Exception as exc:
            details[path] = f"error: {exc}"
            ok = False
    return CheckResult("health_endpoints", ok, details)


def _check_core_smoke(base_url: str) -> CheckResult:
    paths = [
        "/api/images",
        "/api/folders",
        "/api/tags",
        "/api/pending-count",
        "/api/maintenance/duplicates",
        "/api/maintenance/orphans",
        "/api/maintenance/export-csv",
        "/api/maintenance/health-snapshot",
        "/api/maintenance/integrity-scorecard",
        "/api/maintenance/aging-drift",
        "/api/maintenance/quality-drift-queue",
        "/api/maintenance/category-normalization/preview",
        "/api/maintenance/checkpoints",
        "/api/maintenance/scheduled-jobs",
        "/api/maintenance/audit",
        "/api/maintenance/guardrails",
        "/api/maintenance/approvals",
    ]

    statuses: Dict[str, int] = {}
    ok = True
    for p in paths:
        try:
            resp = requests.get(f"{base_url}{p}", timeout=12)
            statuses[p] = resp.status_code
            ok = ok and (resp.status_code == 200)
        except Exception:
            statuses[p] = -1
            ok = False

    return CheckResult("core_smoke_endpoints", ok, {"statuses": statuses})


def _check_pending_consistency(base_url: str) -> CheckResult:
    images = requests.get(f"{base_url}/api/images", timeout=10).json().get("images", [])
    pending_count = requests.get(f"{base_url}/api/pending-count", timeout=10).json().get("count", -1)
    pending_list_count = sum(1 for i in images if i.get("status") == "pending-review")
    ok = pending_count == pending_list_count
    return CheckResult(
        "pending_count_consistency",
        ok,
        {
            "pending_count": pending_count,
            "pending_list_count": pending_list_count,
            "total_images": len(images),
        },
    )


def _check_search_relevance(base_url: str) -> CheckResult:
    images = requests.get(f"{base_url}/api/images", timeout=10).json().get("images", [])
    queries = ["san francisco", "logo", "golden gate"]

    counts: Dict[str, int] = {}
    for q in queries:
        tokens = [t for t in q.lower().split() if t]
        c = 0
        for i in images:
            hay = " ".join([i.get("filename", ""), i.get("alt_text", ""), i.get("tags", "")]).lower()
            if all(tok in hay for tok in tokens):
                c += 1
        counts[q] = c

    ok = all(v > 0 for v in counts.values())
    return CheckResult("search_relevance", ok, {"query_counts": counts})


def _check_thumbnails(base_url: str) -> CheckResult:
    images = requests.get(f"{base_url}/api/images", timeout=10).json().get("images", [])
    broken: List[Dict[str, Any]] = []

    for img in images:
        path = img.get("location", "")
        resp = requests.get(f"{base_url}/thumbnail", params={"path": path}, timeout=10)
        if resp.status_code != 200:
            broken.append({"id": img.get("id"), "location": path, "status": resp.status_code})

    return CheckResult(
        "thumbnail_integrity",
        len(broken) == 0,
        {
            "checked": len(images),
            "broken_count": len(broken),
            "sample": broken[:5],
        },
    )


def _check_status_transitions(base_url: str) -> CheckResult:
    pending = requests.get(
        f"{base_url}/api/images",
        params={"status": "pending-review"},
        timeout=10,
    ).json().get("images", [])

    if not pending:
        return CheckResult("status_transitions", False, {"error": "no pending records in fixture"})

    target = pending[0]
    rid = target["id"]
    transitions = ["approved", "rejected", "archived", "pending-review"]
    steps: List[Dict[str, Any]] = []
    ok = True

    for status in transitions:
        patch = requests.patch(
            f"{base_url}/api/image-status",
            json={"id": rid, "status": status},
            timeout=10,
        )
        images = requests.get(f"{base_url}/api/images", timeout=10).json().get("images", [])
        observed = next((i.get("status") for i in images if i.get("id") == rid), None)
        step_ok = patch.status_code == 200 and observed == status
        ok = ok and step_ok
        steps.append({"status": status, "patch_status": patch.status_code, "observed": observed, "ok": step_ok})

    return CheckResult("status_transitions", ok, {"record_id": rid, "steps": steps})


def _check_batch_approve(base_url: str) -> CheckResult:
    pending = requests.get(
        f"{base_url}/api/images",
        params={"status": "pending-review"},
        timeout=10,
    ).json().get("images", [])

    ids = [p["id"] for p in pending]
    approve_codes = [
        requests.patch(
            f"{base_url}/api/image-status",
            json={"id": rid, "status": "approved"},
            timeout=10,
        ).status_code
        for rid in ids
    ]

    pending_after = requests.get(f"{base_url}/api/pending-count", timeout=10).json().get("count", -1)

    restore_codes = [
        requests.patch(
            f"{base_url}/api/image-status",
            json={"id": rid, "status": "pending-review"},
            timeout=10,
        ).status_code
        for rid in ids
    ]

    ok = all(c == 200 for c in approve_codes) and pending_after == 0 and all(c == 200 for c in restore_codes)

    return CheckResult(
        "approve_all_equivalent",
        ok,
        {
            "pending_before": len(ids),
            "pending_after": pending_after,
            "approve_codes_ok": all(c == 200 for c in approve_codes),
            "restore_codes_ok": all(c == 200 for c in restore_codes),
        },
    )


def _check_concurrency_lock(base_url: str) -> CheckResult:
    images = requests.get(f"{base_url}/api/images", timeout=10).json().get("images", [])
    ids = [i.get("id") for i in images[:4] if i.get("id")]
    if not ids:
        return CheckResult("concurrency_lock_json_integrity", False, {"error": "no records available"})

    def _set_status(record_id: str, status: str) -> int:
        resp = requests.patch(
            f"{base_url}/api/image-status",
            json={"id": record_id, "status": status},
            timeout=10,
        )
        return resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(ids))) as ex:
        codes_a = list(ex.map(lambda rid: _set_status(rid, "approved"), ids))
        codes_b = list(ex.map(lambda rid: _set_status(rid, "pending-review"), ids))

    parse_ok = True
    try:
        _ = json.loads(LOCAL_TABLE_PATH.read_text(encoding="utf-8"))
    except Exception:
        parse_ok = False

    ok = all(c == 200 for c in (codes_a + codes_b)) and parse_ok
    return CheckResult(
        "concurrency_lock_json_integrity",
        ok,
        {
            "set_approved_codes": codes_a,
            "restore_codes": codes_b,
            "json_parse_ok": parse_ok,
        },
    )


def _check_ui_static() -> CheckResult:
    index_html = (REPO_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    review_html = (REPO_ROOT / "templates" / "review.html").read_text(encoding="utf-8")

    checks = {
        "badge_interval_present": "setInterval(refreshReviewBadge, 30000)" in index_html,
        "badge_pageshow_present": "window.addEventListener('pageshow'" in index_html,
        "approve_all_button_present": 'id="approve-all-btn"' in review_html,
        "approve_all_batch_present": "Promise.all(pending.map" in review_html,
        "nested_folder_helper_present": "function locationParent(location)" in index_html,
        "nested_folder_filter_present": "locationParent(img.location)" in index_html,
        "legacy_first_segment_filter_absent": "img.location.split('/')[0]" not in index_html,
        "pagination_container_present": 'id="grid-pagination"' in index_html,
        "load_more_button_present": 'id="grid-load-more"' in index_html,
        "page_size_state_present": "const PAGE_SIZE" in index_html,
    }

    return CheckResult("ui_static_wiring", all(checks.values()), checks)


def _check_nested_folder_counts(base_url: str) -> CheckResult:
    images = requests.get(f"{base_url}/api/images", timeout=10).json().get("images", [])
    folders = requests.get(f"{base_url}/api/folders", timeout=10).json().get("folders", [])

    mismatches: List[Dict[str, Any]] = []
    for folder in folders:
        name = str(folder.get("name", ""))
        if "/" not in name:
            continue
        expected = sum(
            1
            for i in images
            if ("/".join(i.get("location", "").split("/")[:-1]) if "/" in i.get("location", "") else ".") == name
        )
        if expected != int(folder.get("count", -1)):
            mismatches.append({"folder": name, "expected": expected, "reported": folder.get("count")})

    return CheckResult(
        "nested_folder_counts",
        len(mismatches) == 0,
        {
            "nested_folder_count": sum(1 for f in folders if "/" in str(f.get("name", ""))),
            "mismatch_count": len(mismatches),
            "sample": mismatches[:5],
        },
    )


def _check_auth_gate(base_url: str) -> CheckResult:
    details: Dict[str, Any] = {}

    r_api = requests.get(f"{base_url}/api/images", timeout=10)
    details["api_images_status"] = r_api.status_code

    r_root = requests.get(f"{base_url}/", allow_redirects=False, timeout=10)
    details["root_status"] = r_root.status_code
    details["root_location"] = r_root.headers.get("Location", "")

    try:
        r_login = requests.get(f"{base_url}/login", allow_redirects=False, timeout=10)
        details["login_status"] = r_login.status_code
        details["login_location"] = r_login.headers.get("Location", "")
        # In automated local runs, dummy MSAL settings can trigger a 500 on /login
        # because authority discovery is external. Keep this informational only.
        details["login_observed"] = "ok_redirect" if r_login.status_code in (301, 302) else "non_redirect"
    except Exception as exc:
        details["login_status"] = -1
        details["login_location"] = ""
        details["login_observed"] = f"request_error: {exc}"

    ok = (
        r_api.status_code == 401
        and r_root.status_code in (301, 302)
        and r_root.headers.get("Location", "") == "/login"
    )
    return CheckResult("auth_gate_noninteractive", ok, details)


def run_t1_suite(report_file: Optional[Path] = None, local_port: Optional[int] = None, auth_port: Optional[int] = None) -> Dict[str, Any]:
    report_file = report_file or DEFAULT_REPORT_PATH

    original_local_table: Optional[str] = None
    had_local_table = LOCAL_TABLE_PATH.exists()
    if had_local_table:
        original_local_table = LOCAL_TABLE_PATH.read_text(encoding="utf-8")

    checks: List[CheckResult] = []
    skipped: List[Dict[str, Any]] = [
        {
            "id": "msal_valid_invalid_user_browser_flow",
            "reason": "manual interactive validation required",
        },
        {
            "id": "real_token_expiry_window",
            "reason": "manual or long-running auth-session test required",
        },
        {
            "id": "live_azure_sharepoint_validation",
            "reason": "environment-dependent production validation",
        },
    ]
    server_logs: Dict[str, str] = {}

    local_port = local_port or _find_free_port()
    auth_port = auth_port or _find_free_port()

    with tempfile.TemporaryDirectory(prefix="t1-suite-") as td:
        image_root = Path(td) / "assets"
        seeded_records = _seed_dataset(image_root)
        _write_json(LOCAL_TABLE_PATH, seeded_records)

        local_proc: Optional[subprocess.Popen] = None
        auth_proc: Optional[subprocess.Popen] = None
        try:
            local_proc = _start_server(port=local_port, image_root=image_root, bypass_auth=True)
            local_base = f"http://127.0.0.1:{local_port}"
            if not _wait_for_health(local_base):
                raise RuntimeError("Local TEST_MODE server did not become healthy in time")

            checks.append(_check_health(local_base))
            checks.append(_check_core_smoke(local_base))
            checks.append(_check_pending_consistency(local_base))
            checks.append(_check_search_relevance(local_base))
            checks.append(_check_thumbnails(local_base))
            checks.append(_check_status_transitions(local_base))
            checks.append(_check_batch_approve(local_base))
            checks.append(_check_concurrency_lock(local_base))
            checks.append(_check_ui_static())
            checks.append(_check_nested_folder_counts(local_base))

            auth_proc = _start_server(port=auth_port, image_root=image_root, bypass_auth=False)
            auth_base = f"http://127.0.0.1:{auth_port}"
            if not _wait_for_health(auth_base):
                raise RuntimeError("Auth-required TEST_MODE server did not become healthy in time")
            checks.append(_check_auth_gate(auth_base))

        finally:
            if auth_proc is not None:
                server_logs["auth_server_tail"] = _stop_server(auth_proc)
            if local_proc is not None:
                server_logs["local_server_tail"] = _stop_server(local_proc)

    if had_local_table and original_local_table is not None:
        LOCAL_TABLE_PATH.write_text(original_local_table, encoding="utf-8")
    elif LOCAL_TABLE_PATH.exists():
        LOCAL_TABLE_PATH.unlink()

    overall_ok = all(c.ok for c in checks)

    report = {
        "suite": "T1 automated regression",
        "generated_at": _now_iso(),
        "overall_ok": overall_ok,
        "checks": [c.as_dict() for c in checks],
        "skipped": skipped,
        "notes": {
            "coverage": "Automated non-interactive T1 checks only",
            "manual_remaining": [
                "MSAL valid-user browser login",
                "MSAL invalid-user browser login",
                "real token-expiry behavior",
                "live Azure and SharePoint production validation",
            ],
        },
        "server_logs": server_logs,
    }

    _write_json(report_file, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run automated T1 regression suite")
    parser.add_argument(
        "--report-file",
        default=str(DEFAULT_REPORT_PATH),
        help="Path to write JSON report",
    )
    parser.add_argument("--port", type=int, default=0, help="Optional fixed local TEST_MODE port")
    parser.add_argument("--auth-port", type=int, default=0, help="Optional fixed auth-required TEST_MODE port")
    args = parser.parse_args()

    report = run_t1_suite(
        report_file=Path(args.report_file),
        local_port=args.port or None,
        auth_port=args.auth_port or None,
    )

    print(json.dumps(report, indent=2))
    return 0 if report.get("overall_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
