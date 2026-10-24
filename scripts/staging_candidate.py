"""Supervised immutable staging-only comparison; never a production deploy.

Explicit --apply, pinned authenticated receipts, shared release lease, private
backup, cold forward/rollback/forward, unchanged configuration/state. Unknown
mutations retain the lease and durable operator recovery record; no retries.
"""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from scripts.production_azure_adapter import AzureProductionAdapter, API
from scripts.production_release import check_observation, validate_receipt
from scripts.release_artifacts import GitHubReads, load_receipt
from scripts.release_azure_io import ARM, SCM, STORAGE, AzureTransport, AzureIOError, BlobReleaseLease, scm_python_command
from scripts.configure_container_pilot import APP_ID, PLAN_ID
from scripts.rehearsal_runner import CANDIDATE, PRIOR

STAGING_ID = APP_ID + "/slots/staging"


def require(value):
    if not value:
        raise AzureIOError("Staging contract differs; retain lease and reconcile without replay")


class StagingTransport(AzureTransport):
    """No production runtime/file/config writes, settings changes or access grants."""
    def request(self, method, url, **kwargs):
        p = urlsplit(url)
        path = p.path
        arm = p.netloc == urlsplit(ARM).netloc
        arm_read = arm and method == "GET" and (path == PLAN_ID or path == APP_ID or path.startswith(APP_ID + "/"))
        setting_read = arm and method == "POST" and path in {
            APP_ID + "/config/appsettings/list", STAGING_ID + "/config/appsettings/list"}
        staging_write = arm and ((method == "PUT" and path == STAGING_ID + "/sitecontainers/main")
            or (method == "POST" and path in {STAGING_ID + "/stop", STAGING_ID + "/start"}))
        scm = p.netloc == urlsplit(SCM["staging"]).netloc
        scm_read = scm and method == "GET" and path.startswith("/api/vfs/")
        scm_control = scm and method in {"PUT", "DELETE"} and path in {
            "/api/vfs/.image-library-release-control/request.json", "/api/vfs/.image-library-release-control/response.json"}
        # The only SCM command is the existing allowlisted read-only state capture.
        capture = scm and method == "POST" and path == "/api/command" and json.loads(kwargs.get("data", b"{}")) == {
            "command": scm_python_command(Path(__file__).with_name("release_state_archive.py").read_bytes()), "dir": "/home"}
        blob = p.netloc == urlsplit(STORAGE).netloc and (
            (path == "/release-control/production.json" and method in {"GET", "HEAD", "PUT"})
            or (path.startswith("/rollback-backups/") and method in {"GET", "PUT"}))
        require(arm_read or setting_read or staging_write or scm_read or scm_control or capture or blob)
        return super().request(method, url, **kwargs)


def cold_update(adapter, receipt, prior_image, unchanged):
    validate_receipt(receipt)
    require(receipt["registry_image"] in adapter.receipts and receipt["registry_image"] != prior_image)
    life = adapter.lifecycles["staging"]
    unchanged(prior_image)
    old = life.stop()
    unchanged(prior_image)
    adapter.cleanup_channel("staging")
    adapter._assert_channel_absent("staging")
    unchanged(prior_image)
    item = adapter._config("staging")[3]
    require(item.get("name", "").split("/")[-1] == "main")
    properties = deepcopy(item["properties"])
    properties.pop("lastModifiedTime", None)
    properties["image"] = receipt["registry_image"]
    adapter.lease.checkpoint("staging_image_update_requested")
    code, headers, raw = adapter.transport.request("PUT", ARM + STAGING_ID + "/sitecontainers/main?api-version=" + API,
        accepted=(200, 201, 202), headers={"Content-Type": "application/json"}, data=json.dumps({"properties": properties}).encode())
    lower = {k.lower(): v for k, v in headers.items()}
    operation = lower.get("azure-asyncoperation") or lower.get("location")
    if operation:
        require(operation.startswith(ARM + STAGING_ID + "/"))
        adapter.pending_operation = operation
        adapter.pending_kind = "status" if lower.get("azure-asyncoperation") else "location"
        adapter.poll_not_before = time.time() + adapter._poll_delay(lower)
        adapter._await_operation(time.time() + 300)
    else:
        require(code != 202 and (json.loads(raw) if raw else {}).get("properties", {}).get("provisioningState") in {None, "Succeeded"})
    unchanged(receipt["registry_image"])
    life.start()
    adapter._wait_cold_readiness(receipt, time.time() + 300, slot="staging")
    active = life.inventory()
    require(len(active) == 1 and not active & old)
    unchanged(receipt["registry_image"])
    return {"http_status": code, "async_receipt": bool(operation), "fresh_named_runtime": True}


def execute(report):
    token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    receipts = []
    for build in (PRIOR, CANDIDATE):
        api = GitHubReads(token)
        try:
            receipts.append(load_receipt(api, build["run"], build["attempt"], build["commit"], build["image"],
                                         policy_bytes=Path("security/container-review.json").read_bytes()))
        finally:
            api.session.close()
    prior, candidate = receipts
    io = StagingTransport()
    folder = Path(tempfile.mkdtemp(prefix="image-library-staging-release-"))
    report.update(recovery_directory=str(folder), phase="preflight", production_changed=False)
    lease = BlobReleaseLease(io, folder / "owner.json")
    adapter = AzureProductionAdapter(io, lease, candidate, prior)
    production = adapter._cleanup_identity("production")
    initial = adapter._cleanup_identity("staging")
    require(initial["container"]["properties"]["image"] == prior["registry_image"])
    adapter._assert_channel_absent("staging")
    require(len(adapter.lifecycles["staging"].inventory()) == 1)
    lease.initialize()
    with lease.exclusive(APP_ID):
        baseline = adapter.observe("staging")
        check_observation(baseline, "staging", prior)
        require(baseline["active_work"] == 0)
        frozen = adapter.snapshot("staging")
        require(adapter.snapshot("staging") == frozen)
        backup = gzip.compress(json.dumps({"state": frozen, "configuration": initial}, sort_keys=True).encode(), mtime=0)
        url = STORAGE + "/rollback-backups/" + lease.run_id + "/staging.json.gz"
        lease.checkpoint("staging_protected_backup_requested")
        io.request("PUT", url, accepted=(201,), headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, data=backup)
        require(io.request("GET", url, max_bytes=96*1024*1024)[2] == backup)

        def unchanged(image):
            lease.assert_held()
            require(adapter._cleanup_identity("production") == production)
            expected = deepcopy(initial)
            expected["container"]["properties"]["image"] = image
            require(adapter._cleanup_identity("staging") == expected and adapter.snapshot("staging") == frozen)

        previous = baseline
        for phase, receipt, current, protocol in (
            ("candidate_forward", candidate, prior["registry_image"], 2),
            ("controlled_rollback", prior, candidate["registry_image"], 1),
            ("candidate_final", candidate, prior["registry_image"], 2)):
            report["phase"] = phase
            report[phase] = cold_update(adapter, receipt, current, unchanged)
            observed = adapter.observe("staging", protocol=protocol)
            check_observation(observed, "staging", receipt)
            require(observed["active_work"] == 0 and observed["state_id"] == baseline["state_id"]
                    and observed["boot_id"] != previous["boot_id"])
            previous = observed
            unchanged(receipt["registry_image"])
        adapter._assert_channel_absent("staging")
        lease.checkpoint("staging_candidate_verified_read_only")
        report.update(candidate_build=candidate["build_id"], candidate_image=candidate["registry_image"],
                      protected_backup_prefix=lease.run_id, unchanged_configuration_and_state=True)
    _, headers, _ = io.request("HEAD", lease.url)
    require({k.lower(): v for k,v in headers.items()}.get("x-ms-lease-status") == "unlocked")
    report.update(status="passed", lease_released_verified=True,
                  browser_performance_acceptance="pending", production_changed=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.parse_args()
    result = {"status": "started"}
    try:
        execute(result)
    except Exception as error:
        result.update(status="stopped", failure_type=type(error).__name__, instruction="Reconcile; no retry or lease break")
        if isinstance(error, AzureIOError): result["reason"] = str(error)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
