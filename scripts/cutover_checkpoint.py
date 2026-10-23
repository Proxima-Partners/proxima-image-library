"""Supervised cutover backups. No app/config/DNS mutation API.

All return values except the explicit summary contain PRIVATE information.
The caller must hold the production lease and keep those values out of logs.
Default running-app checkpoints are NOT proof of stopped writers or transfer.
Explicit stopped checkpoints require the exact legacy site stopped before/after.
"""
import gzip
import json
from pathlib import Path
import re
import subprocess

from scripts.configure_container_pilot import APP_ID
from scripts.release_azure_io import ARM, LEGACY_SCM, SCM, STORAGE, AzureIOError, scm_python_command
from scripts.release_state_restore import validate

API = "2024-11-01"
MAX_BUNDLE = 96 * 1024 * 1024
LEGACY_ID = APP_ID.rsplit("/", 1)[0] + "/PP-App-Serv"
TARGETS = {
    "legacy-production": (LEGACY_ID, LEGACY_SCM["production"]),
    "legacy-staging": (LEGACY_ID + "/slots/staging", LEGACY_SCM["staging"]),
    "target-production": (APP_ID, SCM["production"]),
    "target-staging": (APP_ID + "/slots/staging", SCM["staging"]),
}


def capture_state(transport, name):
    if name not in TARGETS:
        raise ValueError("Unapproved cutover source")
    source = Path(__file__).with_name("release_state_archive.py").read_bytes()
    command = scm_python_command(source)
    result = transport.json("POST", TARGETS[name][1] + "/api/command",
        body={"command": command, "dir": "/home"}, max_bytes=MAX_BUNDLE, timeout=60)
    if not isinstance(result, dict) or result.get("ExitCode") != 0 or result.get("Error"):
        raise AzureIOError("Private state capture failed; details withheld")
    try:
        bundle = json.loads(result["Output"])
        validate(bundle)
        return bundle
    except (KeyError, TypeError, ValueError):
        raise AzureIOError("Private state capture validation failed") from None


def configuration(transport, name):
    if name not in TARGETS:
        raise ValueError("Unapproved cutover source")
    resource = TARGETS[name][0]
    result = {}
    for key, suffix, method in (
        ("site", "", "GET"), ("web", "/config/web", "GET"),
        ("appsettings", "/config/appsettings/list", "POST"),
        ("connectionstrings", "/config/connectionstrings/list", "POST"),
        ("storageaccounts", "/config/azurestorageaccounts/list", "POST"),
        ("auth", "/config/authsettingsV2", "GET"),
        ("hostbindings", "/hostNameBindings", "GET"),
    ):
        result[key] = transport.json(method, ARM + resource + suffix + "?api-version=" + API)
    if result["site"].get("id", "").lower() != resource.lower():
        raise AzureIOError("Unexpected cutover resource identity")
    if name.startswith("target-"):
        result["containers"] = transport.json("GET", ARM + resource + "/sitecontainers?api-version=" + API)
    return result


def protected_configuration(config):
    # Site operational state can change as Azure reports health; preserve it in
    # the backup but compare the independent configuration resources exactly.
    return {k: v for k, v in config.items() if k != "site"} | {
        "identity": config["site"].get("identity"),
        "plan": config["site"]["properties"].get("serverFarmId"),
    }


def upload_verified(transport, lease, name, value):
    if not re.fullmatch(r"(?:legacy|target)-(?:production|staging)\.(?:json\.gz|source\.tar)", name):
        raise ValueError("Unapproved private backup name")
    if not isinstance(value, bytes) or len(value) > MAX_BUNDLE:
        raise ValueError("Private backup too large")
    url = STORAGE + "/rollback-backups/" + lease.run_id + "/" + name
    lease.assert_held()
    transport.request("PUT", url, accepted=(201,), headers={
        "x-ms-blob-type": "BlockBlob", "If-None-Match": "*",
        "Content-Type": "application/octet-stream"}, data=value)
    _, _, observed = transport.request("GET", url, max_bytes=MAX_BUNDLE)
    if observed != value:
        raise AzureIOError("Private backup readback differs; reconcile without retry")
    return observed


def source_archive(commit):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Full source commit required")
    result = subprocess.run(["git", "archive", "--format=tar", commit], capture_output=True, timeout=60)
    if result.returncode or len(result.stdout) > MAX_BUNDLE:
        raise AzureIOError("Exact rollback source archive unavailable")
    return result.stdout


def checkpoint(transport, lease, name, *, commit, version, stopped=False):
    """Capture + verify private backup, with config/state stable across reads.

    stopped=True requires independent supervisor confirmation of the stopped
    HTTP surface, sole-user quiet window and known source revision; this helper
    additionally verifies the ARM state before/after. It cannot prove prior
    legacy process-level work counts (those revisions have no such counters).
    """
    if (name not in TARGETS or not re.fullmatch(r"[a-f0-9]{40}", commit)
            or type(stopped) is not bool or (stopped and not name.startswith("legacy-"))):
        raise ValueError("Exact approved source and commit required")
    lease.assert_held()
    before = configuration(transport, name)
    if stopped and before["site"]["properties"].get("state") != "Stopped":
        raise AzureIOError("Stopped-writer checkpoint requires a stopped legacy site")
    first = capture_state(transport, name)
    if capture_state(transport, name) != first:
        raise AzureIOError("State changed during preliminary checkpoint")
    after = configuration(transport, name)
    if stopped and after["site"]["properties"].get("state") != "Stopped":
        raise AzureIOError("Legacy site restarted during stopped-writer checkpoint")
    if protected_configuration(after) != protected_configuration(before):
        raise AzureIOError("Configuration changed during preliminary checkpoint")
    bundle = {"schema": 1, "source": name, "commit": commit, "version": version,
        "quiesced": stopped, "containment": "supervised_site_stop" if stopped else "none",
        "transfer_authorized_by_this_checkpoint": False,
        "configuration": before, "state": first}
    private = gzip.compress(json.dumps(bundle, sort_keys=True).encode(), mtime=0)
    lease.checkpoint("preliminary_backup_requested")
    restored = json.loads(gzip.decompress(upload_verified(transport, lease, name + ".json.gz", private)))
    if restored != bundle:
        raise AzureIOError("Private backup decoded readback differs")
    source = source_archive(commit)
    upload_verified(transport, lease, name + ".source.tar", source)
    return restored, {"source": name, "commit": commit, "version": version,
        "private_backup_readback_verified": True, "source_archive_readback_verified": True,
        "state_entries": len(first["entries"]), "state_bytes": first["bytes"],
        "quiesced": stopped, "live_state_transfer": False}
