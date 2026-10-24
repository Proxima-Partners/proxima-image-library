"""One-shot operator diagnosis of the exact failed synthetic rehearsal.

Not a general recovery command. The probe preserves the failed request and uses
its existing lease owner for status-only diagnosis. The separate acceptance
continuation requires that exact successful probe and performs fresh synthetic
resume checks, stopped rollback and owned-file cleanup. All paths are fixed to
the approved isolated app; no settings/provider/production writes or lease break.
Completed private records and lease phases prevent replay of these one-shot steps.
"""
import argparse
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

from scripts import rehearsal_runner as rehearsal
from scripts.release_azure_io import ARM, STORAGE, AzureIOError, AzureTransport, BlobReleaseLease

RUN = "351d2dc4ae084e5c9df9737bb1eaf703"
PREFIX = STORAGE + "/ci-rehearsal/" + RUN
LOCK = STORAGE + "/ci-rehearsal/rehearsal.json"
DRAIN = rehearsal.target.SCM + "/api/vfs/proxima_deployment_drain"
LOG = rehearsal.target.SCM + "/api/vfs/LogFiles/2026_10_24_ln1mdlwk000BAN_docker.log"


class DiagnosticTransport(rehearsal.IsolatedTransport):
    def request(self, method, url, **kwargs):
        if (method == "POST" and url == ARM + rehearsal.target.APP_ID + "/start?api-version=" + rehearsal.target.API
                or method == "GET" and url in {DRAIN, LOG}):
            return AzureTransport.request(self, method, url, **kwargs)
        return super().request(method, url, **kwargs)


def reviewed_configuration(value):
    # The only approved difference since the private snapshot is removal of
    # the exact completed runner's temporary main/SCM ingress rules.
    value = json.loads(json.dumps(value))
    for key in ("ipSecurityRestrictions", "scmIpSecurityRestrictions"):
        rules = value["web"][key]
        value["web"][key] = [r for r in rules if not (
            r.get("name") == "rehearsal-ci-40065382842"
            and r.get("ipAddress") == "20.51.199.49/32" and r.get("action") == "Allow"
            and r.get("priority") == 200)]
    return value


def private_record(io, name, value):
    raw = json.dumps(value, sort_keys=True).encode()
    url = PREFIX + "/" + name
    io.request("PUT", url, accepted=(201,), headers={
        "x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, data=raw)
    rehearsal.require(io.request("GET", url)[2] == raw)


def active_containers(raw):
    """Reconcile named lifecycle starts/deletions in this app's bounded log.

    A deletion request alone is insufficient: require its following termination
    acknowledgement. Ambiguous/interleaved termination records fail closed.
    """
    active, deleting = set(), None
    for line in raw.decode("utf-8").splitlines():
        match = re.search(r"Starting container: ([a-z0-9]+_pp-image-library-rehearsal_main)\.", line)
        if match:
            active.add(match[1])
        match = re.search(r"Deleting container: ([a-z0-9]+_pp-image-library-rehearsal_main)\.", line)
        if match:
            rehearsal.require(deleting is None)
            deleting = match[1]
        if "Container is terminated." in line:
            rehearsal.require(deleting is not None and deleting in active)
            active.remove(deleting)
            deleting = None
    return active


def stopped_runtime(io, lease):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        lease.assert_held()
        if (rehearsal.arm(io)["properties"]["state"] == "Stopped"
                and not active_containers(io.request("GET", LOG, max_bytes=512 * 1024)[2])):
            return
        time.sleep(2)
    raise AzureIOError("Rehearsal process termination not confirmed; no image update")


def recover_owner(io):
    lock = json.loads(io.request("GET", LOCK)[2])
    rehearsal.require(lock["run_id"] == RUN and lock["resource"] == rehearsal.target.APP_ID
        and lock["phase"] == "reconciliation_status_probe_stopped")
    owner = json.loads(io.request("GET", PREFIX + "/owner.json")[2])
    rehearsal.require(owner["run_id"] == RUN and owner["resource"] == rehearsal.target.APP_ID
        and str(uuid.UUID(owner["lease_id"])) == owner["lease_id"])
    lease = BlobReleaseLease(io, Path("unused-owner-record"), blob="rehearsal.json", container="ci-rehearsal")
    lease.run_id, lease.lease_id, lease.acquired = RUN, owner["lease_id"], True
    lease.assert_held()
    return lease


def accept():
    """Fresh synthetic acceptance after the explicitly reconciled status probe."""
    io = DiagnosticTransport()
    previous = json.loads(io.request("GET", PREFIX + "/reconciliation-status-result-v4.json")[2])
    rehearsal.require(previous["status"] == "status_probe_passed" and previous["stopped"] is True
        and len(previous["status_checks"]) == 3)
    lease = recover_owner(io)
    stopped_runtime(io, lease)
    original = json.loads(io.request("GET", PREFIX + "/synthetic-state.json")[2])
    expected_config = reviewed_configuration(original["configuration"])
    rehearsal.require(rehearsal.configuration(io) == expected_config)
    rehearsal.require(rehearsal.arm(io, "/sitecontainers/main")["properties"]["image"] == rehearsal.CANDIDATE["image"])
    rehearsal.require(io.request("GET", DRAIN, max_bytes=1024)[0] == 200)
    rehearsal.require(io.request("GET", rehearsal.FIXTURE)[2] == rehearsal.FIXTURE_BYTES)
    nonces = {value["nonce"] for value in previous["status_checks"]}
    for name in ("request.json", "response.json"):
        value = json.loads(io.request("GET", rehearsal.CONTROL + name)[2])
        rehearsal.require(value["nonce"] in nonces and value["action"] == "status")
    private_record(io, "reconciliation-before-acceptance.json", {
        "configuration": expected_config, "prior_status_probe": previous, "at": int(time.time())})
    report = {"production_changed": False, "original_failed_run_passed": False,
              "operator_recovery_not_ci_acceptance": True, "phase": "candidate_start"}
    try:
        lease.checkpoint("reconciliation_candidate_start")
        rehearsal.arm(io, "/start", method="POST", accepted=(200, 204))
        candidate = dict(rehearsal.CANDIDATE, build_id="40064558508-1")
        rehearsal.ready(candidate, cold_start=True)
        current = rehearsal.control(io, lease, "status", nonces)
        rehearsal.require(current["draining"] is True and current["release"]["build_id"] == candidate["build_id"]
            and current["release_state"]["state_id"] == previous["status_checks"][-1]["release_state"]["state_id"]
            and current["release_state"]["boot_id"] != previous["status_checks"][-1]["release_state"]["boot_id"])
        rehearsal.require(len(active_containers(io.request("GET", LOG, max_bytes=512 * 1024)[2])) == 1)
        exact = dict(commit=candidate["commit"], build_id=candidate["build_id"],
            boot_id=current["release_state"]["boot_id"], state_id=current["release_state"]["state_id"])
        stale = dict(exact, boot_id=previous["status_checks"][-1]["release_state"]["boot_id"])
        report["phase"] = "new_stale_boot_resume"
        denied = rehearsal.control(io, lease, "resume", nonces, expected=stale, ok=False)
        rehearsal.require(denied["draining"] is True and denied["release_state"] == current["release_state"])
        report["stale_boot_denied"] = True
        report["phase"] = "new_exact_resume"
        resumed = rehearsal.control(io, lease, "resume", nonces, expected=exact)
        rehearsal.require(resumed["draining"] is False and resumed["release_state"] == current["release_state"])
        report["exact_resume_passed"] = True
        rehearsal.require(rehearsal.control(io, lease, "drain", nonces)["draining"] is True)
        rehearsal.require(io.request("GET", rehearsal.FIXTURE)[2] == rehearsal.FIXTURE_BYTES
            and rehearsal.configuration(io) == expected_config)
        report["phase"] = "candidate_stop_before_rollback"
        lease.checkpoint("reconciliation_stop_before_rollback")
        rehearsal.arm(io, "/stop", method="POST", accepted=(200, 204))
        stopped_runtime(io, lease)
        report["candidate_termination_verified"] = True
        report["phase"] = "prior_image_update_once"
        report["rollback_arm"] = rehearsal.update(io, lease, rehearsal.PRIOR["image"], candidate["image"],
            {candidate["image"], rehearsal.PRIOR["image"]})
        stopped_runtime(io, lease)
        rehearsal.require(rehearsal.configuration(io) == expected_config)
        report["phase"] = "prior_start_and_verification"
        rehearsal.arm(io, "/start", method="POST", accepted=(200, 204))
        prior = dict(rehearsal.PRIOR, build_id="40019125172-1")
        rehearsal.ready(prior, cold_start=True)
        restored = rehearsal.control(io, lease, "status", nonces)
        rehearsal.require(restored["draining"] is True and restored["release"]["build_id"] == prior["build_id"]
            and restored["release_state"]["state_id"] == current["release_state"]["state_id"]
            and restored["release_state"]["boot_id"] != current["release_state"]["boot_id"])
        rehearsal.require(io.request("GET", rehearsal.FIXTURE)[2] == rehearsal.FIXTURE_BYTES
            and rehearsal.configuration(io) == expected_config)
        report["rollback_verified_held"] = True
        rehearsal.arm(io, "/stop", method="POST", accepted=(200, 204))
        stopped_runtime(io, lease)
        report["phase"] = "owned_fixture_cleanup_after_stop"
        for url in (rehearsal.FIXTURE, rehearsal.CONTROL + "request.json", rehearsal.CONTROL + "response.json"):
            _, headers, raw = io.request("GET", url)
            rehearsal.require(raw == rehearsal.FIXTURE_BYTES if url == rehearsal.FIXTURE else json.loads(raw)["nonce"] in nonces)
            etag = {key.lower(): value for key, value in headers.items()}.get("etag")
            rehearsal.require(bool(etag))
            io.request("DELETE", url, accepted=(200, 204), headers={"If-Match": etag})
            io.request("GET", url, accepted=(404,))
        report.update(status="operator_recovery_passed", stopped=True, owned_fixture_cleanup_verified=True)
        private_record(io, "reconciliation-acceptance-result.json", report)
        lease.release()
        _, headers, _ = io.request("HEAD", LOCK)
        rehearsal.require({k.lower(): v for k, v in headers.items()}.get("x-ms-lease-status") == "unlocked")
        return dict(report, lease_released_verified=True)
    except Exception as error:
        # No rollback on ambiguous resume. Stop only the synthetic writer, once.
        report.update(status="acceptance_stopped_without_replay", failure_type=type(error).__name__)
        if isinstance(error, AzureIOError): report["transport_reason"] = str(error)
        lease.assert_held()
        if rehearsal.arm(io)["properties"]["state"] != "Stopped":
            rehearsal.arm(io, "/stop", method="POST", accepted=(200, 204))
        stopped_runtime(io, lease)
        report.update(stopped=True, lease_retained=True)
        private_record(io, "reconciliation-acceptance-result.json", report)
        return report


def probe():
    run = json.loads(subprocess.check_output([
        "gh", "api", "repos/Proxima-Partners/proxima-image-library/actions/runs/40065382842"], timeout=30))
    rehearsal.require(run["status"] == "completed" and run["conclusion"] == "failure"
        and run["run_attempt"] == 1 and run["head_sha"] == "a9c1f48f111052f98e819201b0d61ddc0f0c47a1")
    io = DiagnosticTransport()
    lock = json.loads(io.request("GET", LOCK)[2])
    rehearsal.require(lock["run_id"] == RUN and lock["resource"] == rehearsal.target.APP_ID
        and lock["phase"] == "reconciliation_status_probe_stopped")
    previous = json.loads(io.request("GET", PREFIX + "/reconciliation-status-result-v3.json")[2])
    rehearsal.require(previous["stopped"] is True and previous["status_checks"] == []
        and previous["status"] == "status_probe_stopped_without_replay"
        and previous["phase"] == "candidate_readiness"
        and previous["failure_type"] == "ReadTimeout")
    owner = json.loads(io.request("GET", PREFIX + "/owner.json")[2])
    rehearsal.require(owner["run_id"] == RUN and owner["resource"] == rehearsal.target.APP_ID
        and str(uuid.UUID(owner["lease_id"])) == owner["lease_id"])
    lease = BlobReleaseLease(io, Path("unused-owner-record"), blob="rehearsal.json", container="ci-rehearsal")
    lease.run_id, lease.lease_id = RUN, owner["lease_id"]
    lease.acquired = True
    lease.assert_held()  # Actual Azure owner renewal; never acquire/break.
    rehearsal.require(rehearsal.arm(io)["properties"]["state"] == "Stopped")
    rehearsal.require(rehearsal.arm(io, "/sitecontainers/main")["properties"]["image"] == rehearsal.CANDIDATE["image"])
    rehearsal.require(io.request("GET", DRAIN, max_bytes=1024)[0] == 200)
    rehearsal.require(io.request("GET", rehearsal.FIXTURE)[2] == rehearsal.FIXTURE_BYTES)
    original = json.loads(io.request("GET", PREFIX + "/synthetic-state.json")[2])
    current = rehearsal.configuration(io)
    rehearsal.require(current == reviewed_configuration(original["configuration"]))
    request = json.loads(io.request("GET", rehearsal.CONTROL + "request.json")[2])
    rehearsal.require(request["action"] == "resume" and request["expires"] < time.time() - 60
        and request["expected"]["build_id"] == "40064558508-1"
        and request["expected"]["commit"] == rehearsal.CANDIDATE["commit"])
    response_code, _, raw = io.request("GET", rehearsal.CONTROL + "response.json", accepted=(200, 404))
    private_record(io, "reconciliation-before-status-v4.json", {
        "failed_request": request, "response_status": response_code,
        "response": json.loads(raw) if response_code == 200 else None,
        "configuration": current, "synthetic_state": rehearsal.FIXTURE_BYTES.decode(),
        "drained": True, "stopped": True, "at": int(time.time())})
    report = {"production_changed": False, "resume_replayed": False, "status_checks": [], "phase": "checkpoint"}
    try:
        lease.checkpoint("reconciliation_drained_start_requested")
        report["phase"] = "start_request"
        rehearsal.arm(io, "/start", method="POST", accepted=(200, 204))
        report["phase"] = "candidate_readiness"
        receipt = dict(rehearsal.CANDIDATE, build_id="40064558508-1")
        rehearsal.ready(receipt, cold_start=True, seconds=180)
        nonces = {request["nonce"]}  # Only the archived, expired request is adopted.
        for _ in range(3):
            report["phase"] = "fresh_status_request"
            value = rehearsal.control(io, lease, "status", nonces)
            rehearsal.require(value["draining"] is True and value["release"]["build_id"] == receipt["build_id"])
            report["status_checks"].append(value)
        rehearsal.require(rehearsal.configuration(io) == current
            and io.request("GET", rehearsal.FIXTURE)[2] == rehearsal.FIXTURE_BYTES)
        report["status"] = "status_probe_passed"
    except Exception as error:
        report["status"] = "status_probe_stopped_without_replay"
        report["failure_type"] = type(error).__name__
        if isinstance(error, AzureIOError):
            # This transport's exceptions contain fixed descriptions/statuses,
            # never Azure response bodies, credentials or SDK exception text.
            report["transport_reason"] = str(error)
    finally:
        # Containment of the synthetic app is allowed even when a reply is lost.
        # Stop is issued once, not retried; the held lease remains on all paths.
        lease.assert_held()
        rehearsal.arm(io, "/stop", method="POST", accepted=(200, 204))
        report["stopped"] = rehearsal.arm(io)["properties"]["state"] == "Stopped"
        rehearsal.require(report["stopped"])
        private_record(io, "reconciliation-status-result-v4.json", report)
        lease.checkpoint("reconciliation_status_probe_stopped")
    return {"status": report["status"], "acknowledged_status_checks": len(report["status_checks"]),
            "stopped": report["stopped"], "lease_retained": True, "production_changed": False,
            "phase": report["phase"], "failure_type": report.get("failure_type"),
            "transport_reason": report.get("transport_reason")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true")
    group.add_argument("--accept", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(accept() if args.accept else probe()))
    except Exception:
        print(json.dumps({"status": "reconcile_without_replay", "lease_retained": True}))
        raise SystemExit(1)
