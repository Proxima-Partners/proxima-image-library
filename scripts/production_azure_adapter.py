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
from scripts.production_release import validate_receipt, check_observation, ConfirmedVerificationFailure, StopRelease
from scripts.release_azure_io import ARM, SCM, STORAGE, AzureIOError, scm_python_command
from scripts.production_lifecycle import ProductionLifecycle
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
        self.lifecycle = ProductionLifecycle(transport, lease)
        self.lifecycles = {"production": self.lifecycle,
                           "staging": ProductionLifecycle(transport, lease, slot="staging")}
        self.update_uncertain = False
        self.start_required = False
        self.cleanup_attempted = False
        self.cleanup_complete = False
        self.resume_attempted = False
        self.resume_complete = False
        self.prepared_resume = None
        self.one_shot_uncertain = False

    def _arm(self, slot, suffix="", *, method="GET", body=None):
        if slot not in SCM:
            raise AzureIOError("Unapproved Image Library slot")
        resource = APP_ID + ("/slots/staging" if slot == "staging" else "")
        return self.transport.json(method, ARM + resource + suffix + "?api-version=" + API, body=body)

    @contextmanager
    def exclusive(self, resource):
        with self.lease.exclusive(resource):
            yield
            if (not self.cleanup_complete or self.one_shot_uncertain
                    or (self.resume_attempted and not self.resume_complete)):
                raise AzureIOError("Stopped cleanup acceptance missing; retain lease")

    def validate_resume_policy(self, resume_writes):
        if resume_writes and self._config("production")[1].get("PRODUCTION_RELEASE_RESUME_ENABLED") != "true":
            raise AzureIOError("Automatic resume has not been approved/configured")

    def assert_lease(self):
        self.lease.assert_held()

    def _rpc(self, slot, action, *, expected=None, protocol=1):
        self.assert_lease()
        if type(protocol) is not int or protocol not in {1, 2}:
            raise AzureIOError("Unapproved control protocol")
        if protocol == 2 and self.one_shot_uncertain:
            raise AzureIOError("One-shot outcome uncertain; no replay")
        if self.cleanup_attempted and not (self.cleanup_complete and protocol == 2
                and slot == "production" and action in {"probe", "resume"}):
            raise AzureIOError("Control channel is sealed after cleanup begins")
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
            if protocol == 2:
                raise AzureIOError("One-shot channel is not empty; reconcile")
            try:
                prior = json.loads(prior)
            except ValueError:
                raise AzureIOError("Unrecognized prior control request; reconcile first") from None
            if not isinstance(prior, dict) or prior.get("nonce") not in self.nonces[slot]:
                raise AzureIOError("Unrecognized prior control request; reconcile first")
        condition = {"If-Match": etag} if status == 200 else {"If-None-Match": "*"}
        if protocol == 2:
            self._assert_channel_absent(slot)
        body = {"protocol": protocol, "nonce": nonce, "expires": int(self.clock()) + 60, "action": action}
        if action == "resume":
            body["expected"] = expected
        self.lease.checkpoint("runtime_" + action + "_requested")
        if protocol == 2:
            self.one_shot_uncertain = True
        self.transport.request("PUT", url, accepted=(200, 201, 204), headers=condition,
                               data=json.dumps(body).encode())
        deadline = self.clock() + 45
        response_url = SCM[slot] + "/api/vfs/" + DIRECTORY + "/response.json"
        while self.clock() < deadline:
            self.assert_lease()
            status, response_headers, raw = self.transport.request("GET", response_url, accepted=(200, 404), max_bytes=8192)
            if status == 200:
                try:
                    result = json.loads(raw)
                except ValueError:
                    raise AzureIOError("Invalid runtime control response") from None
                if not isinstance(result, dict):
                    raise AzureIOError("Invalid runtime control response")
                if result.get("nonce") == nonce:
                    if (type(result.get("protocol")) is not int or result.get("protocol") != protocol or result.get("action") != action
                            or result.get("slot") != slot or result.get("ok") is not True
                            or type(result.get("at")) is not int or not 0 <= self.clock() - result["at"] <= 45):
                        raise AzureIOError("Runtime control failed or response is stale")
                    if protocol == 2:
                        response_etag = {k.lower(): v for k, v in response_headers.items()}.get("etag")
                        if result.get("request_retired") is not True or not response_etag:
                            raise AzureIOError("One-shot retirement acknowledgement missing")
                        self.transport.request("GET", url, accepted=(404,), max_bytes=4096)
                        self.assert_lease()
                        self.lease.checkpoint("one_shot_response_delete_requested")
                        self.transport.request("DELETE", response_url, accepted=(200, 204),
                                               headers={"If-Match": response_etag})
                        self._assert_channel_absent(slot)
                        self.one_shot_uncertain = False
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

    def observe(self, slot, *, protocol=1):
        site, settings, web, main = self._config(slot)
        runtime = self._rpc(slot, "probe", protocol=protocol)
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
        if self.pending_operation or self.update_uncertain or self.start_required or self.cleanup_attempted:
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
        # Set before the first mutation: an unknown stop/PUT must not be replayed,
        # including by a caller that catches the exception and reuses this object.
        self.update_uncertain = True
        self.lifecycle.stop()
        self.assert_lease()
        if self._config("production")[3] != item:
            raise AzureIOError("Container changed while stopping; reconcile")
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
        self.update_uncertain = False
        self.start_required = True
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
        if self.update_uncertain:
            raise AzureIOError("Image outcome uncertain; no start permitted")
        if self.start_required:
            if self.clock() >= deadline:
                raise AzureIOError("Verification deadline exhausted; no start permitted")
            self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
            # Clear only after acknowledgement. An uncertain start is terminal.
            self.update_uncertain = True
            self.lifecycle.start()
            self.start_required = False
            self._wait_cold_readiness(receipt, deadline)
            self.update_uncertain = False
        while self.clock() < deadline:
            self.assert_lease()
            if self.configuration() != configuration:
                raise AzureIOError("Configuration changed during verification")
            # Ambiguous SCM/network results intentionally propagate: no blind
            # retry/rollback after a transport failure. Restart-window 404/503
            # handling must be proven in rehearsal before widening this policy.
            observed = self.observe("production")
            if observed["commit"] == receipt["commit"] and observed["build_id"] == receipt["build_id"]:
                if len(self.lifecycle.inventory()) != 1:
                    raise AzureIOError("Expected exactly one named production runtime")
                self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
                if not observed["healthy"] or not observed["auth_verified"] or not observed["reads_verified"]:
                    raise ConfirmedVerificationFailure("Confirmed runtime acceptance failure")
                return observed
            self.pause(3)
        raise ConfirmedVerificationFailure("Acknowledged update did not become the expected ready build")

    def _wait_cold_readiness(self, receipt, deadline, *, slot="production"):
        # Only idempotent public GETs are retried. 401/403/redirects are not
        # accepted as a restart transient; access failures need reconciliation.
        if slot not in SCM:
            raise AzureIOError("Unapproved readiness slot")
        host = "https://pp-image-library" + ("-staging" if slot == "staging" else "") + ".azurewebsites.net"
        with requests.Session() as session:
            session.trust_env = False
            while self.clock() < deadline:
                self.assert_lease()
                try:
                    with session.get(host + "/readyz",
                            timeout=(5, min(15, deadline - self.clock())),
                            allow_redirects=False, stream=True) as response:
                        if response.status_code == 200:
                            raw = response.raw.read(32769, decode_content=True)
                            if len(raw) > 32768:
                                raise AzureIOError("Readiness response exceeds bound")
                            value = json.loads(raw)
                            if (value.get("commit") == receipt["commit"]
                                    and value.get("build_id") == receipt["build_id"]
                                    and value.get("version") == "v2.0.0"
                                    and value.get("telemetry") is True
                                    and value.get("status") == "ready"):
                                return
                        elif response.status_code not in {502, 503}:
                            raise AzureIOError("Cold readiness access refused")
                except (requests.Timeout, requests.ConnectionError):
                    pass
                self.pause(min(3, max(0, deadline - self.clock())))
        raise AzureIOError("Cold readiness unconfirmed; reconcile without mutation")

    def prepare_resume(self, receipt, previous, configuration, frozen):
        self.validate_resume_policy(True)
        if not self.cleanup_complete or self.resume_attempted:
            raise AzureIOError("Post-cleanup verification required before resume")
        self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
        fresh = self.observe("production", protocol=2)
        check_observation(fresh, "production", receipt, drained=True)
        if fresh["state_id"] != previous["state_id"] or fresh["boot_id"] == previous["boot_id"]:
            raise AzureIOError("Post-cleanup mount or fresh boot differs")
        if len(self.lifecycle.inventory()) != 1:
            raise AzureIOError("Post-cleanup runtime overlap")
        self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
        self.prepared_resume = deepcopy(fresh)
        return fresh

    def resume_verified(self, receipt, observed, configuration, frozen):
        self.validate_resume_policy(True)
        if self.resume_attempted or self.prepared_resume is None or observed != self.prepared_resume:
            raise AzureIOError("Exact post-cleanup resume preparation required; no retry")
        self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
        validate_receipt(receipt)
        self.resume_attempted = True
        expected = {key: observed[key] for key in ("commit", "build_id", "boot_id", "state_id")}
        result = self._rpc("production", "resume", expected=expected, protocol=2)
        if (result.get("draining") is not False or result.get("release_state") != {
                key: observed[key] for key in ("state_id", "boot_id", "uid", "gid")}
                or result.get("release", {}).get("commit") != receipt["commit"]
                or result.get("release", {}).get("build_id") != receipt["build_id"]):
            raise AzureIOError("Exact resume acknowledgement differs; reconcile without retry")
        # Writes can begin immediately. Never compare/restore the frozen files
        # or restart after sending resume, including on verification ambiguity.
        current = self.observe("production", protocol=2)
        check_observation(current, "production", receipt, drained=False)
        if current["boot_id"] != observed["boot_id"] or current["state_id"] != observed["state_id"]:
            raise AzureIOError("Runtime changed after resume; reconcile without mutation")
        if self.configuration() != configuration or len(self.lifecycle.inventory()) != 1:
            raise AzureIOError("Configuration/runtime changed after resume")
        self.resume_complete = True
        return current

    def cleanup_channel(self, slot="production"):
        # Deleting a request while its reader is running can recreate a response
        # after deletion. Refuse that race; cleanup orchestration must supply a
        # separately verified stopped lifecycle, never infer it from idle work.
        if slot not in SCM:
            raise AzureIOError("Unapproved cleanup slot")
        lifecycle = self.lifecycle if slot == "production" else self.lifecycles[slot]
        lifecycle.confirm_stopped()
        nonces = self.nonces[slot]
        for name in ("request.json", "response.json"):
            self.assert_lease()
            url = SCM[slot] + "/api/vfs/" + DIRECTORY + "/" + name
            status, headers, raw = self.transport.request("GET", url, accepted=(200, 404), max_bytes=8192)
            if status == 404:
                continue
            data = json.loads(raw)
            etag = {k.lower(): v for k, v in headers.items()}.get("etag")
            if not isinstance(data, dict) or data.get("nonce") not in nonces or not etag:
                raise AzureIOError("Control files changed; preserve for reconciliation")
            self.assert_lease()
            self.lease.checkpoint(slot + "_control_delete_requested")
            self.transport.request("DELETE", url, accepted=(200, 204), headers={"If-Match": etag})
            self.transport.request("GET", url, accepted=(404,), max_bytes=8192)

    def _cleanup_identity(self, slot):
        site, settings, web, main = self._config(slot)
        web, main = deepcopy(web), deepcopy(main)
        web.pop("lastModifiedTime", None)
        main["properties"].pop("lastModifiedTime", None)
        return {"settings": settings, "web": web, "container": main,
                "identity": site.get("identity"),
                "site": {key: site["properties"].get(key) for key in
                         ("serverFarmId", "httpsOnly", "clientCertEnabled", "publicNetworkAccess")},
                "auth": self._arm(slot, "/config/authsettingsV2"),
                "hostnames": self._arm(slot, "/hostNameBindings")}

    def _assert_channel_absent(self, slot):
        for name in ("request.json", "response.json"):
            self.transport.request("GET", SCM[slot] + "/api/vfs/" + DIRECTORY + "/" + name,
                                   accepted=(404,), max_bytes=8192)

    def _check_public_auth(self, slot):
        host = "https://pp-image-library" + ("-staging" if slot == "staging" else "") + ".azurewebsites.net"
        with requests.Session() as session:
            session.trust_env = False
            root = session.get(host + "/", timeout=(5, 15), allow_redirects=False)
            admin = session.get(host + "/api/maintenance/deployment-status", timeout=(5, 15), allow_redirects=False)
        if root.status_code != 302 or root.headers.get("Location") != "/login" or admin.status_code != 401:
            raise AzureIOError("Cleanup restart authentication boundary differs")

    def finalize_held(self, receipt, configuration, frozen):
        """Stop/delete/restart once, with no RPC after deletion to recreate files.

        Called explicitly before the controller journals success. Any uncertainty
        retains the lease and prohibits replay, restart, resume or rollback.
        """
        if self.cleanup_attempted or self.update_uncertain or self.pending_operation or self.start_required:
            raise AzureIOError("Cleanup cannot start or be replayed")
        self.cleanup_attempted = True
        self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
        for slot in ("staging", "production"):
            if not self.nonces[slot]:
                continue
            self.assert_lease()
            identity = self._cleanup_identity(slot)
            image = identity["container"]["properties"]["image"]
            if image not in self.receipts:
                raise AzureIOError("Cleanup image lacks verified provenance")
            expected = self.receipts[image]
            validate_receipt(expected)
            snapshot = self.snapshot(slot)
            lifecycle = self.lifecycle if slot == "production" else self.lifecycles[slot]

            def unchanged():
                self.assert_lease()
                if self._cleanup_identity(slot) != identity or self.snapshot(slot) != snapshot:
                    raise AzureIOError("Cleanup configuration/state changed; reconcile")
                if slot == "production":
                    self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)

            unchanged()
            old = lifecycle.stop()
            unchanged()
            self.cleanup_channel(slot)
            unchanged()
            validate_receipt(expected)
            lifecycle.start()
            self._wait_cold_readiness(expected, self.clock() + 300, slot=slot)
            active = lifecycle.inventory()
            if len(active) != 1 or active & old:
                raise AzureIOError("Cleanup restart lacks one fresh named runtime")
            unchanged()
            self._check_public_auth(slot)
            self._assert_channel_absent(slot)
            self.lease.checkpoint(slot + "_cleanup_restart_verified")
        self.assert_recovery_safe(receipt["registry_image"], configuration, frozen)
        self.cleanup_complete = True
