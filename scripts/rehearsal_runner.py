"""Real CI-path rehearsal on the separately approved synthetic Azure app only.

Never a production deployment command. ARM mutations are hard limited to the
rehearsal container/stop endpoint; SCM and storage are isolated. Unknown mutation
outcomes retain the infinite lease and private recovery record. The report does
not claim real-provider catalog/SSO acceptance or complete production promotion.
"""
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

import requests

from scripts import rehearsal_infra as target
from scripts import rehearsal_lifecycle as lifecycle
from scripts.production_azure_adapter import AzureProductionAdapter
from scripts.release_artifacts import GitHubReads, load_receipt
from scripts.release_azure_io import ARM, STORAGE, AzureIOError, AzureTransport, BlobReleaseLease

CANDIDATE = {"run": 40064558508, "attempt": 1, "commit": "ba61c526f522349ad6bfdbbd39d76448078bb91d",
             "image": "proximaimagelibrary.azurecr.io/image-library@sha256:f5ad233782189bf29457b52ee1394a04f0209640cf8672fc68c42690524f9c12"}
PRIOR = {"run": 40019125172, "attempt": 1, "commit": "2ffc0ff18ad191d1ccc1c185b4ce848b9442de4b", "image": target.PRIOR_IMAGE}
CONTROL = target.SCM + "/api/vfs/.image-library-release-control/"
FIXTURE = target.SCM + "/api/vfs/proxima_ss_counter.json"
FIXTURE_BYTES = b'{"rehearsal":"synthetic-only","count":7}\n'


def require(condition):
    if not condition:
        raise AzureIOError("Rehearsal contract differs; reconcile without replay")


class IsolatedTransport(AzureTransport):
    """Physical target fence in addition to the dedicated principal's RBAC."""
    def request(self, method, url, **kwargs):
        p = urlsplit(url)
        app = ARM + target.APP_ID
        arm_read = method == "GET" and (url.startswith(app + "?") or url.startswith(app + "/")
            or url.startswith(ARM + target.PLAN_ID + "?"))
        arm_write = ((method == "PUT" and url.startswith(app + "/sitecontainers/main?"))
                     or (method == "POST" and (url.startswith(app + "/stop?") or url.startswith(app + "/start?")
                         or url.startswith(app + "/config/appsettings/list?"))))
        scm = url in {CONTROL + "request.json", CONTROL + "response.json", FIXTURE}
        blob = p.netloc == urlsplit(STORAGE).netloc and (p.path.startswith("/ci-rehearsal/")
            or (p.path == "/ci-rehearsal" and method in {"GET", "HEAD"}))
        require(arm_read or arm_write or scm or blob or lifecycle.log_read_allowed(method, url))
        return super().request(method, url, **kwargs)


def arm(io, suffix="", method="GET", body=None, **kwargs):
    return io.json(method, ARM + target.APP_ID + suffix + "?api-version=" + target.API, body=body, **kwargs)


def immutable_container(value):
    props = dict(value["properties"])
    props.pop("lastModifiedTime", None)
    require(props.get("isMain") is True and props.get("authType") == "SystemIdentity"
            and str(props.get("targetPort")) == "8080")
    require(not any(props.get(k) for k in ("startUpCommand", "environmentVariables", "volumeMounts")))
    return props


def configuration(io):
    settings = arm(io, "/config/appsettings/list", method="POST")["properties"]
    require(all(settings.get(k) == v for k, v in {
        "TEST_MODE": "false", "DEV_AUTH_BYPASS": "false", "INGEST_POLLER_ENABLED": "false",
        "PRODUCTION_RELEASE_CONTROL_ENABLED": "true", "PRODUCTION_RELEASE_RESUME_ENABLED": "true",
        "APP_STATE_DIR": "/home", "TELEMETRY_ENABLED": "false", "STORAGE_MODE": "local"}.items()))
    require(not any(value for key, value in settings.items() if key.startswith(
        ("SHAREPOINT_", "MSAL_CLIENT", "ANTHROPIC_", "MCP_INTERNAL"))))
    container = immutable_container(arm(io, "/sitecontainers/main"))
    container.pop("image")
    web = arm(io, "/config/web")["properties"]
    web.pop("lastModifiedTime", None)
    require(web.get("ipSecurityRestrictionsDefaultAction") == web.get("scmIpSecurityRestrictionsDefaultAction") == "Deny")
    return {"settings": settings, "container": container, "web": web}


def control(io, lease, action, nonces, *, expected=None, ok=True, protocol=1):
    require(action in {"status", "state_probe", "drain", "resume"})
    require(type(protocol) is int and protocol in {1, 2})
    lease.assert_held()
    code, headers, raw = io.request("GET", CONTROL + "request.json", accepted=(200, 404), max_bytes=4096)
    etag = {k.lower(): v for k, v in headers.items()}.get("etag")
    if code == 200:
        require(protocol == 1)
        require(json.loads(raw).get("nonce") in nonces and bool(etag))
    if protocol == 2:
        io.request("GET", CONTROL + "response.json", accepted=(404,), max_bytes=8192)
    nonce = uuid.uuid4().hex
    nonces.add(nonce)
    payload = {"protocol": protocol, "nonce": nonce, "expires": int(time.time()) + 60, "action": action}
    if expected is not None:
        payload["expected"] = expected
    lease.checkpoint("rehearsal_runtime_" + action + "_requested")
    io.request("PUT", CONTROL + "request.json", accepted=(200, 201, 204),
        headers={"If-Match": etag} if code == 200 else {"If-None-Match": "*"}, data=json.dumps(payload).encode())
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        lease.assert_held()
        code, response_headers, raw = io.request("GET", CONTROL + "response.json", accepted=(200, 404), max_bytes=8192)
        if code == 200:
            value = json.loads(raw)
            if value.get("nonce") == nonce:
                require(value.get("ok") is ok and value.get("action") == action and value.get("protocol") == protocol
                        and value.get("slot") == "production" and value.get("workers") == 1
                        and value.get("active_work") == 0 and value.get("read_only") is False
                        and 0 <= time.time() - value["at"] <= 45)
                if protocol == 2:
                    response_etag = {k.lower(): v for k, v in response_headers.items()}.get("etag")
                    require(value.get("request_retired") is True and bool(response_etag))
                    io.request("GET", CONTROL + "request.json", accepted=(404,), max_bytes=4096)
                    lease.assert_held()
                    lease.checkpoint("rehearsal_one_shot_response_delete_requested")
                    io.request("DELETE", CONTROL + "response.json", accepted=(200, 204),
                               headers={"If-Match": response_etag})
                    for name in ("request.json", "response.json"):
                        io.request("GET", CONTROL + name, accepted=(404,), max_bytes=8192)
                return value
        time.sleep(1)
    raise AzureIOError("Runtime reply unknown; no replay")


def ready(receipt, *, seconds=300, cold_start=False):
    # Readiness GET polling is not a retry of a write. Restart 502/503 is explicit.
    deadline = time.monotonic() + seconds
    with requests.Session() as session:
        session.trust_env = False
        while time.monotonic() < deadline:
            try:
                with session.get(target.HOST + "/readyz", timeout=(5, 15), allow_redirects=False, stream=True) as response:
                    if response.status_code == 200:
                        raw = response.raw.read(32769, decode_content=True)
                        require(len(raw) <= 32768)
                        value = json.loads(raw)
                        if value.get("commit") == receipt["commit"] and value.get("build_id") == receipt["build_id"]:
                            require(value.get("status") == "ready" and value.get("version") == "v2.0.0")
                            return value
                    elif response.status_code not in ({403, 502, 503} if cold_start else {502, 503}):
                        raise AzureIOError(f"Unexpected readiness status (HTTP {response.status_code})")
            except (requests.Timeout, requests.ConnectionError):
                # Bounded, idempotent GET only. Never repeat an ARM/SCM write.
                pass
            time.sleep(3)
    raise AzureIOError("Exact rehearsal readiness missing; reconcile")


def update(io, lease, image, expected_current, allowed_images):
    require(image in allowed_images and image != expected_current)
    lease.assert_held()
    item = arm(io, "/sitecontainers/main")
    properties = immutable_container(item)
    require(properties["image"] == expected_current)
    properties["image"] = image
    lease.checkpoint("rehearsal_image_update_requested")
    code, headers, raw = io.request("PUT", ARM + target.APP_ID + "/sitecontainers/main?api-version=" + target.API,
        accepted=(200, 201, 202), headers={"Content-Type": "application/json"}, data=json.dumps({"properties": properties}).encode())
    lower = {k.lower(): v for k, v in headers.items()}
    operation = lower.get("azure-asyncoperation") or lower.get("location")
    if operation:
        require(operation.startswith(ARM + target.APP_ID + "/"))
        # Exercise the production adapter's bounded poll implementation unchanged.
        pending = SimpleNamespace(transport=io, assert_lease=lease.assert_held, clock=time.time,
            pause=time.sleep, pending_operation=operation,
            pending_kind="status" if lower.get("azure-asyncoperation") else "location",
            poll_not_before=time.time() + AzureProductionAdapter._poll_delay(lower),
            _poll_delay=AzureProductionAdapter._poll_delay)
        AzureProductionAdapter._await_operation(pending, time.time() + 300)
    else:
        require(code != 202)
        value = json.loads(raw) if raw else {}
        require(value.get("properties", {}).get("provisioningState") in {None, "Succeeded"})
    require(immutable_container(arm(io, "/sitecontainers/main")) == properties)
    return {"http_status": code, "async_receipt": bool(operation)}


def cold_update(io, lease, receipt, expected_current, allowed_images):
    # ARM's one-instance setting permits old/new containers to overlap during
    # an online update. Explicit downtime plus named termination evidence is
    # required here; per-container Gunicorn counts do not fence the old worker.
    lifecycle.stop(io, lease)
    result = update(io, lease, receipt["registry_image"], expected_current, allowed_images)
    lifecycle.confirm_stopped(io, lease)
    lease.checkpoint("rehearsal_start_requested")
    arm(io, "/start", method="POST", accepted=(200, 204))
    ready(receipt, cold_start=True)
    require(len(lifecycle.inventory(io)) == 1)
    return dict(result, stopped_update=True, prior_termination_verified=True)


def cleanup_restart(io, lease, receipt, nonces, expected_configuration):
    """Rehearse stopped owned-file cleanup; never delete a running RPC request."""
    def unchanged():
        lease.assert_held()
        require(configuration(io) == expected_configuration)
        require(arm(io, "/sitecontainers/main")["properties"]["image"] == receipt["registry_image"])
        require(io.request("GET", FIXTURE)[2] == FIXTURE_BYTES)

    unchanged()
    old = lifecycle.inventory(io)
    lifecycle.stop(io, lease)
    unchanged()
    for name in ("request.json", "response.json"):
        url = CONTROL + name
        code, headers, raw = io.request("GET", url, accepted=(200, 404), max_bytes=8192)
        if code == 404:
            continue
        etag = {k.lower(): v for k, v in headers.items()}.get("etag")
        require(json.loads(raw).get("nonce") in nonces and bool(etag))
        lease.assert_held()
        lease.checkpoint("rehearsal_stopped_control_delete_requested")
        io.request("DELETE", url, accepted=(200, 204), headers={"If-Match": etag})
        io.request("GET", url, accepted=(404,), max_bytes=8192)
    unchanged()
    lifecycle.confirm_stopped(io, lease)
    lease.checkpoint("rehearsal_cleanup_restart_requested")
    arm(io, "/start", method="POST", accepted=(200, 204))
    ready(receipt, cold_start=True)
    active = lifecycle.inventory(io)
    require(len(active) == 1 and not active & old)
    unchanged()
    for name in ("request.json", "response.json"):
        io.request("GET", CONTROL + name, accepted=(404,), max_bytes=8192)


def execute(report=None):
    require(os.getenv("IMAGE_LIBRARY_RECOVERY_REHEARSAL_ENABLED") == "true"
            and os.getenv("GITHUB_REF") == "refs/heads/main"
            and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.getenv("GITHUB_RUN_ATTEMPT") == "1")
    report = report if report is not None else {}
    report.update(status="started", physical_target=target.APP_NAME, production_changed=False,
                  provider_credentials_used=False, production_acceptance=False, phase="receipt_verification")
    policy = Path("security/container-review.json").read_bytes()
    receipts = []
    for build in (PRIOR, CANDIDATE):
        api = GitHubReads(os.environ["GH_TOKEN"])
        try:
            receipts.append(load_receipt(api, build["run"], build["attempt"], build["commit"], build["image"], policy_bytes=policy))
        finally:
            api.session.close()
    prior, candidate = receipts
    report["phase"] = "target_preflight"
    io = IsolatedTransport()
    app = arm(io)
    require(app["id"].lower() == target.APP_ID.lower()
            and app["properties"]["serverFarmId"].lower() == target.PLAN_ID.lower())
    original_configuration = configuration(io)
    require(arm(io, "/sitecontainers/main")["properties"]["image"] == prior["registry_image"])
    with tempfile.TemporaryDirectory(prefix="image-library-recovery-") as folder:
        lease = BlobReleaseLease(io, Path(folder) / "owner.json", blob="rehearsal.json", container="ci-rehearsal")
        prefix = STORAGE + "/ci-rehearsal/" + lease.run_id
        owner = json.dumps({"lease_id": lease.lease_id, "run_id": lease.run_id, "resource": target.APP_ID,
                            "instruction": "Reconcile exact rehearsal target; never auto-break"}).encode()
        io.request("PUT", prefix + "/owner.json", accepted=(201,), headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, data=owner)
        require(io.request("GET", prefix + "/owner.json")[2] == owner)
        report["phase"] = "lease_initialization"
        lease.initialize()
        report["phase"] = "lease_acquisition"
        with lease.exclusive(target.APP_ID):
            nonces = set()
            report["phase"] = "prior_cold_start"
            # Start from a stopped, non-overlapping runtime after network-rule
            # changes too. The private lease is held before every lifecycle write.
            lifecycle.stop(io, lease)
            lease.checkpoint("rehearsal_prior_start_requested")
            arm(io, "/start", method="POST", accepted=(200, 204))
            ready(prior, cold_start=True)
            require(len(lifecycle.inventory(io)) == 1)
            code, _, _ = io.request("PUT", lease.url + "?comp=lease", accepted=(409,), headers={
                "x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1", "x-ms-proposed-lease-id": str(uuid.uuid4())})
            report["lease_contention_rejected"] = code == 409
            before = control(io, lease, "status", nonces)
            # A reconciled prior rollback deliberately remains drained.
            require(type(before["draining"]) is bool and before["release"]["build_id"] == prior["build_id"])
            probe = control(io, lease, "state_probe", nonces)["state_probe"]
            require(probe["uid"] == probe["gid"] == 65532 and probe["cleanup_verified"] and probe["read_write_rename"])
            io.request("GET", FIXTURE, accepted=(404,))
            io.request("PUT", FIXTURE, accepted=(200, 201, 204), headers={"If-None-Match": "*"}, data=FIXTURE_BYTES)
            require(control(io, lease, "drain", nonces)["draining"] is True)
            require(io.request("GET", FIXTURE)[2] == FIXTURE_BYTES)
            backup = json.dumps({"configuration": original_configuration, "synthetic_state": FIXTURE_BYTES.decode()}, sort_keys=True).encode()
            io.request("PUT", prefix + "/synthetic-state.json", accepted=(201,),
                headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, data=backup)
            require(io.request("GET", prefix + "/synthetic-state.json")[2] == backup)
            report["protected_synthetic_backup_readback"] = True
            report["phase"] = "forward_cold_update"
            report["forward_arm"] = cold_update(io, lease, candidate, prior["registry_image"], {r["registry_image"] for r in receipts})
            require(configuration(io) == original_configuration)
            after = control(io, lease, "status", nonces)
            require(after["draining"] is True and after["release"]["build_id"] == candidate["build_id"])
            require(after["release_state"]["state_id"] == before["release_state"]["state_id"]
                    and after["release_state"]["boot_id"] != before["release_state"]["boot_id"])
            require(io.request("GET", FIXTURE)[2] == FIXTURE_BYTES)
            report["phase"] = "candidate_stopped_cleanup_restart"
            cleanup_restart(io, lease, candidate, nonces, original_configuration)
            fresh = control(io, lease, "status", nonces, protocol=2)
            require(fresh["draining"] is True and fresh["release"] == after["release"]
                    and fresh["release_state"]["state_id"] == after["release_state"]["state_id"]
                    and fresh["release_state"]["boot_id"] != after["release_state"]["boot_id"])
            report["stopped_cleanup_restart_verified"] = True
            exact = {"commit": candidate["commit"], "build_id": candidate["build_id"],
                     "boot_id": fresh["release_state"]["boot_id"], "state_id": fresh["release_state"]["state_id"]}
            stale = dict(exact, boot_id=after["release_state"]["boot_id"])
            report["phase"] = "stale_boot_resume_denial"
            require(control(io, lease, "resume", nonces, expected=stale, ok=False, protocol=2)["draining"] is True)
            report["phase"] = "exact_resume"
            require(control(io, lease, "resume", nonces, expected=exact, protocol=2)["draining"] is False)
            verified = control(io, lease, "status", nonces, protocol=2)
            require(verified["draining"] is False and verified["release_state"] == fresh["release_state"])
            report["one_shot_post_cleanup_resume_verified"] = True
            report["exact_resume_and_stale_rejection"] = True
            require(control(io, lease, "drain", nonces)["draining"] is True)
            require(io.request("GET", FIXTURE)[2] == FIXTURE_BYTES)
            require(configuration(io) == original_configuration)
            report["phase"] = "rollback_cold_update"
            report["rollback_arm"] = cold_update(io, lease, prior, candidate["registry_image"], {r["registry_image"] for r in receipts})
            require(configuration(io) == original_configuration)
            restored = control(io, lease, "status", nonces)
            require(restored["draining"] is True and restored["release"]["build_id"] == prior["build_id"])
            require(restored["release_state"]["state_id"] == before["release_state"]["state_id"]
                    and restored["release_state"]["boot_id"] != after["release_state"]["boot_id"])
            # Stop before deleting the channel: no runtime can recreate a reply.
            lifecycle.stop(io, lease)
            report["phase"] = "owned_fixture_cleanup"
            for url in (FIXTURE, CONTROL + "request.json", CONTROL + "response.json"):
                _, headers, raw = io.request("GET", url)
                require(raw == FIXTURE_BYTES if url == FIXTURE else json.loads(raw).get("nonce") in nonces)
                etag = {k.lower(): v for k, v in headers.items()}.get("etag"); require(bool(etag))
                io.request("DELETE", url, accepted=(200, 204), headers={"If-Match": etag})
                io.request("GET", url, accepted=(404,))
            report.update(rollback_verified_held=True, synthetic_fixture_cleanup_verified=True, private_record_prefix=lease.run_id)
        code, headers, _ = io.request("HEAD", lease.url)
        require({k.lower(): v for k, v in headers.items()}.get("x-ms-lease-status") == "unlocked")
        report["lease_released_verified"] = True
    # Only the separate rehearsal app is stopped, after exact rollback/cleanup.
    require(arm(io)["properties"]["state"] == "Stopped")
    report.update(status="passed", rehearsal_stopped=True,
                  not_assessed=["production_catalog_or_sso", "production_controller_end_to_end", "continuous_telemetry", "stable_unattended_runner_network"])
    return report


if __name__ == "__main__":
    result = {}
    try:
        execute(result)
    except Exception as error:
        result.update(status="stopped", reason="reconcile_rehearsal_state_no_retry_or_lease_break",
                      production_changed=False, failure_type=type(error).__name__)
        # Fixed transport descriptions only, never remote bodies/SDK exceptions.
        if isinstance(error, AzureIOError): result["transport_reason"] = str(error)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/recovery-rehearsal.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "passed" else 1)
