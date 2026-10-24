"""Draft Azure/SCM adapter; NOT approved for production execution.

Not a cutover command: requires production already on the release-channel image,
ingestion disabled, staging validated, and current CI-bound receipt objects.
No public machine-admin endpoint or automatic state restore. Write resumption
requires an explicit controller option AND separately approved runtime setting.
The authenticated artifact loader exists; CI access proof and live recovery
rehearsal remain required. There is no deployment CLI or workflow entry point.
"""
from contextlib import contextmanager
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid

import requests

from scripts.configure_container_pilot import APP_ID, PLAN_ID
from scripts.production_release import validate_receipt, ConfirmedVerificationFailure, StopRelease
from scripts.release_azure_io import ARM, SCM, STORAGE, AzureIOError, scm_python_command
from src.release_channel import DIRECTORY

API = "2024-11-01"
MAX_BUNDLE = 96 * 1024 * 1024


class VerifiedReceipt(dict):
    """Locally matched metadata, not a substitute for trusted artifact retrieval."""


def verify_receipt_provenance(receipt, run, *, artifact_name):
    validate_receipt(receipt)
    expected = f"{run.get('id')}-{run.get('run_attempt')}"
    identity = (run.get("head_branch"), run.get("path"), artifact_name)
    approved = {
        ("perf/container-pilot", ".github/workflows/container-pilot.yml", "pilot-build-" + expected),
        ("main", ".github/workflows/production-build.yml", "production-build-" + expected),
    }
    if (run.get("repository", {}).get("full_name") != "Proxima-Partners/proxima-image-library"
            or run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("head_sha") != receipt["commit"] or receipt["build_id"] != expected
            or identity not in approved
            or receipt.get("provenance_type") != "workflow-release-receipt"
            or type(receipt.get("unreviewed_high_critical")) is not int
            or receipt.get("unreviewed_high_critical") != 0
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", receipt.get("image_config_id", ""))):
        raise StopRelease("CI receipt provenance differs from approved build workflow")
    return VerifiedReceipt(deepcopy(receipt))


class AzureProductionAdapter:
    def __init__(self, transport, lease, candidate, prior, *, clock=time.time, pause=time.sleep):
        if not all(isinstance(r, VerifiedReceipt) for r in (candidate, prior)):
            raise StopRelease("Verified CI receipts required; arbitrary local JSON is not provenance")
        self.transport, self.lease = transport, lease
        self.receipts = {r["registry_image"]: deepcopy(r) for r in (candidate, prior)}
        self.clock, self.pause = clock, pause
        self.nonces = {"production": set(), "staging": set()}
        self.pending_operation = None
        self.pending_kind, self.poll_not_before = "status", 0

    def _arm(self, slot, suffix="", *, method="GET", body=None):
        if slot not in SCM:
            raise AzureIOError("Unapproved Image Library slot")
        resource = APP_ID + ("/slots/staging" if slot == "staging" else "")
        return self.transport.json(method, ARM + resource + suffix + "?api-version=" + API, body=body)

    @contextmanager
    def exclusive(self, resource):
        with self.lease.exclusive(resource):
            yield
            self.cleanup_channel()

    def assert_lease(self):
        self.lease.assert_held()

    def _rpc(self, slot, action, *, expected=None):
        self.assert_lease()
        if (slot not in SCM or action not in {"status", "probe", "state_probe", "drain", "resume"}
                or (action in {"drain", "resume"} and slot != "production")):
            raise AzureIOError("Unapproved runtime control action")
        if action == "resume":
            if (not isinstance(expected, dict) or set(expected) != {"commit", "build_id", "boot_id", "state_id"}
                    or not re.fullmatch(r"[a-f0-9]{40}", str(expected["commit"]))
                    or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", str(expected["build_id"]))
                    or not re.fullmatch(r"[a-f0-9]{32}", str(expected["boot_id"]))
                    or not re.fullmatch(r"[a-f0-9]{64}", str(expected["state_id"]))):
                raise AzureIOError("Exact resume binding is required")
        elif expected is not None:
            raise AzureIOError("Unexpected runtime control arguments")
        nonce = uuid.uuid4().hex
        self.nonces[slot].add(nonce)
        url = SCM[slot] + "/api/vfs/" + DIRECTORY + "/request.json"
        status, headers, prior = self.transport.request("GET", url, accepted=(200, 404), max_bytes=4096)
        etag = {k.lower(): v for k, v in headers.items()}.get("etag")
        if status == 200 and not etag:
            raise AzureIOError("Missing request-file ETag")
        if status == 200:
            try:
                prior = json.loads(prior)
            except ValueError:
                raise AzureIOError("Unrecognized prior control request; reconcile first") from None
            if not isinstance(prior, dict) or prior.get("nonce") not in self.nonces[slot]:
                raise AzureIOError("Unrecognized prior control request; reconcile first")
        condition = {"If-Match": etag} if status == 200 else {"If-None-Match": "*"}
        body = {"protocol": 1, "nonce": nonce, "expires": int(self.clock()) + 60, "action": action}
        if action == "resume":
            body["expected"] = expected
        self.lease.checkpoint("runtime_" + action + "_requested")
        self.transport.request("PUT", url, accepted=(200, 201, 204), headers=condition,
                               data=json.dumps(body).encode())
        deadline = self.clock() + 45
        response_url = SCM[slot] + "/api/vfs/" + DIRECTORY + "/response.json"
        while self.clock() < deadline:
            self.assert_lease()
            status, _, raw = self.transport.request("GET", response_url, accepted=(200, 404), max_bytes=8192)
            if status == 200:
                try:
                    result = json.loads(raw)
                except ValueError:
                    raise AzureIOError("Invalid runtime control response") from None
                if not isinstance(result, dict):
                    raise AzureIOError("Invalid runtime control response")
                if result.get("nonce") == nonce:
                    if (type(result.get("protocol")) is not int or result.get("protocol") != 1 or result.get("action") != action
                            or result.get("slot") != slot or result.get("ok") is not True
                            or type(result.get("at")) is not int or not 0 <= self.clock() - result["at"] <= 45):
                        raise AzureIOError("Runtime control failed or response is stale")
                    return result
            self.pause(1)
        raise AzureIOError("Runtime control deadline exceeded; do not repeat the mutation")

    def _config(self, slot):
        site = self._arm(slot)
        expected_id = APP_ID + ("/slots/staging" if slot == "staging" else "")
        p = site["properties"]
        if site["id"].lower() != expected_id.lower() or p["serverFarmId"].lower() != PLAN_ID.lower():
            raise AzureIOError("Unexpected app or shared plan")
        settings = self._arm(slot, "/config/appsettings/list", method="POST")["properties"]
        web = self._arm(slot, "/config/web")["properties"]
        items = self._arm(slot, "/sitecontainers")["value"]
        if len(items) != 1:
            raise AzureIOError("Exactly one site container is required")
        container = items[0]["properties"]
        if (container.get("isMain") is not True or str(container.get("targetPort")) != "8080"
                or container.get("authType") != "SystemIdentity"
                or any(container.get(k) for k in ("startUpCommand", "environmentVariables", "volumeMounts"))):
            raise AzureIOError("Unexpected container execution overrides")
        required = {"TEST_MODE": "false", "DEV_AUTH_BYPASS": "false", "INGEST_POLLER_ENABLED": "false",
                    "PRODUCTION_RELEASE_CONTROL_ENABLED": "true", "PILOT_STATE_PROBE_ENABLED": "false",
                    "WEBSITES_ENABLE_APP_SERVICE_STORAGE": "true", "APP_STATE_DIR": "/home",
                    "TELEMETRY_SLOT": slot, "TELEMETRY_ENABLED": "true",
                    "APP_READ_ONLY": "true" if slot == "staging" else "false"}
        if any(settings.get(k) != v for k, v in required.items()):
            raise AzureIOError("Unsafe production release configuration")
        return site, settings, web, items[0]

    def configuration(self):
        site, settings, web, main = self._config("production")
        container = deepcopy(main["properties"])
        container.pop("image", None)
        container.pop("lastModifiedTime", None)
        web = deepcopy(web)
        web.pop("lastModifiedTime", None)
        return {"settings": settings, "web": web, "container": container,
                "identity": site.get("identity"),
                "site": {k: site["properties"].get(k) for k in ("serverFarmId", "httpsOnly", "clientCertEnabled", "publicNetworkAccess")},
                "auth": self._arm("production", "/config/authsettingsV2")["properties"],
                "hostnames": self._arm("production", "/hostNameBindings")["value"]}

    def observe(self, slot):
        site, settings, web, main = self._config(slot)
        runtime = self._rpc(slot, "probe")
        host = site["properties"]["defaultHostName"]
        expected_host = "pp-image-library" + ("-staging" if slot == "staging" else "") + ".azurewebsites.net"
        if host != expected_host:
            raise AzureIOError("Unexpected runtime hostname")
        with requests.Session() as session:
            session.trust_env = False
            root = session.get("https://" + host + "/", timeout=(5, 15), allow_redirects=False)
            admin = session.get("https://" + host + "/api/maintenance/deployment-status", timeout=(5, 15), allow_redirects=False)
            ready = session.get("https://" + host + "/readyz", timeout=(5, 15), allow_redirects=False)
        info = ready.json() if ready.status_code == 200 else {}
        if info.get("commit") != runtime["release"].get("commit") or info.get("build_id") != runtime["release"].get("build_id"):
            raise AzureIOError("Public readiness and authenticated process identity differ")
        plan = self.transport.json("GET", ARM + PLAN_ID + "?api-version=" + API)
        state = runtime["release_state"]
        if slot == "production":
            prior_state = getattr(self, "observed_state_id", state["state_id"])
            if state["state_id"] != prior_state:
                raise AzureIOError("Production mount changed during release")
            self.observed_state_id = state["state_id"]
        return {"resource": APP_ID + ("/slots/staging" if slot == "staging" else ""), "plan": PLAN_ID,
                "slot": slot, "capacity": plan["sku"]["capacity"], "workers": runtime.get("workers"),
                "image": main["properties"]["image"], "commit": runtime["release"]["commit"],
                "build_id": runtime["release"]["build_id"], "version": runtime["release"]["version"],
                **state, "read_only": runtime["read_only"], "draining": runtime["draining"],
                "active_work": runtime["active_work"], "ingest_enabled": False, "release_controls": True,
                "pilot_probe": False, "healthy": info.get("status") == "ready" and info.get("telemetry") is True,
                "auth_verified": root.status_code == 302 and root.headers.get("Location") == "/login" and admin.status_code == 401,
                "reads_verified": type(runtime.get("sample_records")) is int and runtime["sample_records"] in (0, 1)}

    def drain(self):
        return self._rpc("production", "drain").get("draining") is True

    def snapshot(self, slot="production"):
        if slot not in SCM:
            raise AzureIOError("Unexpected state source")
        source = Path(__file__).with_name("release_state_archive.py").read_bytes()
        command = scm_python_command(source)
        result = self.transport.json("POST", SCM[slot] + "/api/command",
                                     body={"command": command, "dir": "/home"}, max_bytes=MAX_BUNDLE, timeout=60)
        if result.get("ExitCode") != 0 or result.get("Error"):
            raise AzureIOError("State capture refused; details withheld")
        try:
            return json.loads(result["Output"])
        except (KeyError, ValueError):
            raise AzureIOError("Invalid state capture") from None

    def freeze_state(self):
        self.assert_lease()
        runtime = self._rpc("production", "status")
        if runtime.get("draining") is not True or type(runtime.get("active_work")) is not int or runtime["active_work"] != 0:
            raise AzureIOError("State capture requires confirmed idle drain")
        if runtime["release_state"]["state_id"] != getattr(self, "observed_state_id", None):
            raise AzureIOError("Production mount differs from pre-drain observation")
        self.frozen_state_id = self.observed_state_id
        self._check_sentinel()
        first = self.snapshot()
        if first != self.snapshot():
            raise AzureIOError("State was not stable after drain")
        config = self.configuration()
        value = gzip.compress(json.dumps({"state": first, "configuration": config}, sort_keys=True).encode(), mtime=0)
        url = STORAGE + "/rollback-backups/" + self.lease.run_id + "/production.json.gz"
        self.lease.checkpoint("protected_backup_requested")
        self.transport.request("PUT", url, accepted=(201,), headers={"x-ms-blob-type": "BlockBlob",
            "If-None-Match": "*", "Content-Type": "application/gzip"}, data=value)
        _, _, observed = self.transport.request("GET", url, max_bytes=MAX_BUNDLE)
        if hashlib.sha256(observed).digest() != hashlib.sha256(value).digest():
            raise AzureIOError("Protected backup verification failed")
        return first

    def _check_sentinel(self):
        _, _, marker = self.transport.request("GET", SCM["production"] + "/api/vfs/.image-library-release-state", max_bytes=33)
        if (not re.fullmatch(rb"[a-f0-9]{32}", marker)
                or hashlib.sha256(marker).hexdigest() != getattr(self, "frozen_state_id", None)):
            raise AzureIOError("Persistent mount identity changed or was not checkpointed")

    def assert_recovery_safe(self, image, configuration, frozen):
        self.assert_lease()
        if self.configuration() != configuration or self._config("production")[3]["properties"]["image"] != image:
            raise AzureIOError("Concurrent protected configuration or image change")
        # Independent of the app process/readiness. A persistent marker alone
        # is insufficient: the exact frozen application files must still match.
        self.transport.request("GET", SCM["production"] + "/api/vfs/proxima_deployment_drain", max_bytes=1024)
        self._check_sentinel()
        if self.snapshot() != frozen:
            raise AzureIOError("Protected files changed; no automatic rollback")

    def update(self, image):
        self.assert_lease()
        if self.pending_operation:
            raise AzureIOError("Previous ARM operation unresolved; reconcile before another update")
        if image not in self.receipts:
            raise AzureIOError("Image lacks verified CI provenance")
        validate_receipt(self.receipts[image])
        _, _, _, item = self._config("production")
        if item.get("name", "").split("/")[-1] != "main":
            raise AzureIOError("Unexpected container name")
        properties = deepcopy(item["properties"])
        properties["image"] = image
        properties.pop("lastModifiedTime", None)
        self.lease.checkpoint("image_update_requested")
        status, headers, raw = self.transport.request("PUT", ARM + APP_ID + "/sitecontainers/main?api-version=" + API,
                               accepted=(200, 201, 202), headers={"Content-Type": "application/json"},
                               data=json.dumps({"properties": properties}).encode())
        lower = {key.lower(): value for key, value in headers.items()}
        operation = lower.get("azure-asyncoperation") or lower.get("location")
        if operation:
            parsed = urlsplit(operation)
            prefix = ARM + APP_ID.split("/resourceGroups/")[0] + "/"
            if not operation.startswith(prefix) or parsed.fragment or parsed.username:
                raise AzureIOError("Unapproved ARM operation poll endpoint; reconcile")
            self.pending_operation = operation
            self.pending_kind = "status" if lower.get("azure-asyncoperation") else "location"
            self.poll_not_before = self.clock() + self._poll_delay(lower)
        elif status == 202:
            raise AzureIOError("ARM accepted without a poll receipt; outcome requires reconciliation")
        else:
            try:
                result = json.loads(raw) if raw else {}
                state = result.get("properties", {}).get("provisioningState")
                if state not in (None, "Succeeded"):
                    raise ValueError("nonterminal or failed ARM state")
            except (ValueError, TypeError, AttributeError):
                raise AzureIOError("ARM result is not confirmed synchronous; reconcile") from None
            self.pending_operation = None
        return True

    @staticmethod
    def _poll_delay(headers):
        value = headers.get("retry-after", "3")
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,6}", value):
            raise AzureIOError("Unrecognized ARM polling interval; reconcile")
        return max(1, int(value))  # Never shorten a provider-requested interval.

    def _await_operation(self, deadline):
        while self.pending_operation:
            self.assert_lease()
            if self.clock() >= deadline:
                raise AzureIOError("ARM operation still uncertain; no automatic rollback")
            if self.poll_not_before > self.clock():
                self.pause(min(3, self.poll_not_before - self.clock(), deadline - self.clock()))
                continue
            code, headers, raw = self.transport.request("GET", self.pending_operation,
                accepted=(200, 202, 204), timeout=min(30, deadline - self.clock()))
            if self.clock() >= deadline:
                raise AzureIOError("ARM polling deadline exceeded; reconcile")
            lower = {key.lower(): value for key, value in headers.items()}
            try:
                result = json.loads(raw) if raw else {}
                if not isinstance(result, dict) or not isinstance(result.get("properties", {}), dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise AzureIOError("Unrecognized ARM polling response; reconcile") from None
            state = result.get("status") or result.get("properties", {}).get("provisioningState")
            if ((state == "Succeeded" and code == 200)
                    or (self.pending_kind == "location" and code in {200, 204} and state is None)):
                self.pending_operation = None
            elif (state in {"InProgress", "Running", "Accepted"}
                  or (self.pending_kind == "location" and code == 202 and state is None)):
                self.poll_not_before = self.clock() + self._poll_delay(lower)
            else:
                raise AzureIOError("ARM terminal result needs reconciliation; no blind rollback")

    def verify(self, receipt, baseline, configuration, frozen, *, seconds):
        deadline = self.clock() + seconds
        self._await_operation(deadline)
        while self.clock() < deadline:
            self.assert_lease()
            if self.configuration() != configuration:
                raise AzureIOError("Configuration changed during verification")
            # Ambiguous SCM/network results intentionally propagate: no blind
            # retry/rollback after a transport failure. Restart-window 404/503
            # handling must be proven in rehearsal before widening this policy.
            observed = self.observe("production")
            if observed["commit"] == receipt["commit"] and observed["build_id"] == receipt["build_id"]:
                self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
                if not observed["healthy"] or not observed["auth_verified"] or not observed["reads_verified"]:
                    raise ConfirmedVerificationFailure("Confirmed runtime acceptance failure")
                return observed
            self.pause(3)
        raise ConfirmedVerificationFailure("Acknowledged update did not become the expected ready build")

    def resume_verified(self, receipt, observed, configuration, frozen):
        self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
        if self._config("production")[1].get("PRODUCTION_RELEASE_RESUME_ENABLED") != "true":
            raise AzureIOError("Automatic resume has not been approved/configured")
        expected = {key: observed[key] for key in ("commit", "build_id", "boot_id", "state_id")}
        result = self._rpc("production", "resume", expected=expected)
        if result.get("draining") is not False:
            raise AzureIOError("Resume not acknowledged; reconcile without retry")
        # Writes may have begun after resume. Never compare/restore the old file
        # snapshot now, and never enter rollback after a resume ambiguity.
        return self.observe("production")

    def cleanup_channel(self):
        for slot, nonces in self.nonces.items():
            for name in ("request.json", "response.json"):
                self.assert_lease()
                url = SCM[slot] + "/api/vfs/" + DIRECTORY + "/" + name
                status, headers, raw = self.transport.request("GET", url, accepted=(200, 404), max_bytes=8192)
                if status == 404:
                    continue
                data = json.loads(raw)
                etag = {k.lower(): v for k, v in headers.items()}.get("etag")
                if data.get("nonce") not in nonces or not etag:
                    raise AzureIOError("Control files changed; preserve for reconciliation")
                self.transport.request("DELETE", url, accepted=(200, 204), headers={"If-Match": etag})
                self.transport.request("GET", url, accepted=(404,), max_bytes=8192)
