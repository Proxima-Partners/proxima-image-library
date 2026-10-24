from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import production_azure_adapter as azure


def receipt(letter="a", build="123-1"):
    return {"status": "pass", "registry_image": "proximaimagelibrary.azurecr.io/image-library@sha256:" + letter * 64,
            "commit": letter * 40, "build_id": build,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "provenance_type": "workflow-release-receipt", "unreviewed_high_critical": 0,
            "image_config_id": "sha256:" + letter * 64}


def run():
    return {"id": 123, "run_attempt": 1, "repository": {"full_name": "Proxima-Partners/proxima-image-library"},
            "status": "completed", "conclusion": "success", "head_sha": "a" * 40,
            "head_branch": "perf/container-pilot", "path": ".github/workflows/container-pilot.yml"}


def test_receipt_metadata_must_match_exact_successful_build():
    result = azure.verify_receipt_provenance(receipt(), run(), artifact_name="pilot-build-123-1")
    assert isinstance(result, azure.VerifiedReceipt)


@pytest.mark.parametrize("key,value", [("conclusion", "failure"), ("status", "in_progress"),
    ("head_sha", "b" * 40), ("head_branch", "main"), ("run_attempt", 2),
    ("path", ".github/workflows/unreviewed.yml"), ("repository", {"full_name": "other/repo"})])
def test_untrusted_run_rejected(key, value):
    evidence = run()
    evidence[key] = value
    with pytest.raises(azure.StopRelease):
        azure.verify_receipt_provenance(receipt(), evidence, artifact_name="pilot-build-123-1")


@pytest.mark.parametrize("key,value", [("unreviewed_high_critical", False), ("unreviewed_high_critical", 1),
    ("provenance_type", "self-attested"), ("image_config_id", "unbound"), ("build_id", "124-1")])
def test_mismatched_receipt_rejected(key, value):
    data = receipt()
    data[key] = value
    with pytest.raises(azure.StopRelease):
        azure.verify_receipt_provenance(data, run(), artifact_name="pilot-build-123-1")


@pytest.fixture
def adapter():
    # Test fixtures only; the production controller has no CLI entry point.
    lease = SimpleNamespace(assert_held=lambda: None, checkpoint=lambda phase: None, run_id="test-run")
    transport = SimpleNamespace(request=lambda *a, **k: (_ for _ in ()).throw(AssertionError("Unexpected network call")))
    return azure.AzureProductionAdapter(transport, lease,
        azure.VerifiedReceipt(receipt("b", "124-1")), azure.VerifiedReceipt(receipt()), clock=lambda: 1000)


def config():
    return ({"id": azure.APP_ID, "properties": {"serverFarmId": azure.PLAN_ID}}, {}, {},
            {"name": "main", "properties": {"image": receipt()["registry_image"], "targetPort": "8080",
            "isMain": True, "authType": "SystemIdentity", "lastModifiedTime": "old"}})


def test_arbitrary_receipt_dicts_rejected():
    with pytest.raises(azure.StopRelease):
        azure.AzureProductionAdapter(None, None, receipt(), receipt("b"))


@pytest.mark.parametrize("slot,action", [("legacy", "status"), ("staging", "drain"),
    ("production", "undrain"), ("production", "exec")])
def test_rpc_scope_before_mutation(adapter, slot, action):
    with pytest.raises(azure.AzureIOError):
        adapter._rpc(slot, action)


def test_rpc_nonce_freshness_and_conditional_write(adapter):
    calls, command = [], {}
    def request(method, url, **kwargs):
        calls.append((method, kwargs))
        if method == "PUT":
            command.update(json.loads(kwargs["data"]))
            return 201, {}, b""
        if url.endswith("request.json"):
            return 404, {}, b""
        return 200, {}, json.dumps(dict(command, ok=True, slot="production", at=1000)).encode()
    adapter.transport.request = request
    assert adapter._rpc("production", "status")["nonce"] in adapter.nonces["production"]
    assert next(kwargs for method, kwargs in calls if method == "PUT")["headers"] == {"If-None-Match": "*"}


def test_rpc_does_not_overwrite_another_run(adapter):
    adapter.transport.request = lambda *a, **k: (200, {"ETag": '"known"'}, b'{"nonce":"other"}')
    with pytest.raises(azure.AzureIOError, match="prior control"):
        adapter._rpc("production", "status")


def test_config_guards_and_immutable_update_only(adapter, monkeypatch):
    captured = []
    monkeypatch.setattr(adapter, "_config", lambda slot: deepcopy(config()))
    adapter.transport.request = lambda *args, **kwargs: captured.append((args, kwargs)) or (200, {}, b"")
    candidate = receipt("b", "124-1")["registry_image"]
    assert adapter.update(candidate) is True
    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[0] == "PUT" and args[1].startswith(azure.ARM + azure.APP_ID + "/sitecontainers/main?")
    body = json.loads(kwargs["data"])["properties"]
    assert body["image"] == candidate and body["targetPort"] == "8080"
    assert "lastModifiedTime" not in body
    with pytest.raises(azure.AzureIOError):
        adapter.update("unapproved")
    assert len(captured) == 1


def test_update_transport_failure_is_not_retried(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "_config", lambda slot: deepcopy(config()))
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        raise azure.AzureIOError("unknown")
    adapter.transport.request = fail
    with pytest.raises(azure.AzureIOError):
        adapter.update(receipt()["registry_image"])
    assert len(calls) == 1


def test_async_update_without_operation_receipt_is_ambiguous(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "_config", lambda slot: deepcopy(config()))
    adapter.transport.request = lambda *a, **k: (202, {}, b"")
    with pytest.raises(azure.AzureIOError, match="poll receipt"):
        adapter.update(receipt()["registry_image"])


@pytest.mark.parametrize("raw", [b'{"properties":{"provisioningState":"InProgress"}}',
    b'{"properties":{"provisioningState":"Failed"}}', b'[]', b'not json'])
def test_sync_status_with_uncertain_body_is_not_an_acknowledgement(adapter, monkeypatch, raw):
    monkeypatch.setattr(adapter, "_config", lambda slot: deepcopy(config()))
    adapter.transport.request = lambda *a, **k: (201, {}, raw)
    with pytest.raises(azure.AzureIOError, match="reconcile"):
        adapter.update(receipt()["registry_image"])


def test_pending_arm_operation_blocks_a_second_mutation(adapter, monkeypatch):
    adapter.pending_operation = azure.ARM + azure.APP_ID + "/operations/fixture"
    monkeypatch.setattr(adapter, "_config", lambda _: pytest.fail("no more calls"))
    with pytest.raises(azure.AzureIOError, match="unresolved"):
        adapter.update(receipt()["registry_image"])


def test_async_update_must_complete_before_runtime_verification(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "_config", lambda slot: deepcopy(config()))
    url = azure.ARM + azure.APP_ID + "/operations/fixture?api-version=" + azure.API
    adapter.transport.request = lambda *a, **k: (202, {"Azure-AsyncOperation": url}, b"")
    assert adapter.update(receipt()["registry_image"]) is True
    assert adapter.pending_operation == url
    values, times = iter([{"status": "InProgress"}, {"status": "Succeeded"}]), [1000]
    adapter.transport.request = lambda *a, **k: (200, {}, json.dumps(next(values)).encode())
    adapter.clock = lambda: times[0]
    adapter.pause = lambda seconds: times.__setitem__(0, times[0] + seconds)
    adapter._await_operation(1010)
    assert adapter.pending_operation is None and times[0] == 1006


@pytest.mark.parametrize("state", ["Failed", "Canceled", "Unknown", None])
def test_async_failed_or_unknown_state_stops_without_automatic_rollback(adapter, state):
    adapter.pending_operation = azure.ARM + azure.APP_ID + "/operations/fixture"
    adapter.transport.request = lambda *a, **k: (200, {}, json.dumps({"status": state}).encode())
    with pytest.raises(azure.AzureIOError): adapter._await_operation(1010)
    assert adapter.pending_operation is not None


def test_async_deadline_is_not_confirmed_runtime_failure(adapter):
    adapter.pending_operation = azure.ARM + azure.APP_ID + "/operations/fixture"
    with pytest.raises(azure.AzureIOError): adapter._await_operation(999)


@pytest.mark.parametrize("terminal", [200, 204])
def test_location_poll_honors_retry_after_and_empty_terminal_result(adapter, terminal):
    adapter.pending_operation = azure.ARM + azure.APP_ID + "/operations/fixture"
    adapter.pending_kind = "location"
    times, calls = [1000], []
    values = iter([(202, {"Retry-After": "7"}, b""), (terminal, {}, b"")])
    def request(*a, **k): calls.append(times[0]); return next(values)
    adapter.transport.request = request
    adapter.clock = lambda: times[0]
    adapter.pause = lambda delay: times.__setitem__(0, times[0] + delay)
    adapter._await_operation(1020)
    assert calls == [1000, 1007] and adapter.pending_operation is None


def test_long_retry_after_stops_without_an_early_poll(adapter):
    adapter.pending_operation = azure.ARM + azure.APP_ID + "/operations/fixture"
    adapter.pending_kind = "location"
    times, calls = [1000], []
    def request(*a, **k): calls.append(times[0]); return 202, {"Retry-After": "30"}, b""
    adapter.transport.request = request
    adapter.clock = lambda: times[0]
    adapter.pause = lambda delay: times.__setitem__(0, times[0] + delay)
    with pytest.raises(azure.AzureIOError): adapter._await_operation(1010)
    assert calls == [1000] and adapter.pending_operation is not None


@pytest.mark.parametrize("header", ["invalid", "-1", "1.5"])
def test_invalid_polling_interval_is_not_guessed(adapter, header):
    with pytest.raises(azure.AzureIOError): adapter._poll_delay({"retry-after": header})


def test_empty_status_endpoint_does_not_mean_success(adapter):
    adapter.pending_operation = azure.ARM + azure.APP_ID + "/operations/fixture"
    adapter.transport.request = lambda *a, **k: (204, {}, b"")
    with pytest.raises(azure.AzureIOError): adapter._await_operation(1010)


def test_foreign_operation_poll_is_rejected(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "_config", lambda slot: deepcopy(config()))
    adapter.transport.request = lambda *a, **k: (202, {"Location": "https://evil.test/poll"}, b"")
    with pytest.raises(azure.AzureIOError): adapter.update(receipt()["registry_image"])


def test_resume_requires_separate_runtime_approval(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "assert_recovery_safe", lambda *a: None)
    monkeypatch.setattr(adapter, "_config", lambda slot: deepcopy(config()))
    monkeypatch.setattr(adapter, "_rpc", lambda *a, **k: pytest.fail("resume forbidden"))
    with pytest.raises(azure.AzureIOError, match="approved"):
        adapter.resume_verified(receipt(), {}, {}, {})


def test_protected_backup_roundtrip_and_independent_mount(adapter, monkeypatch):
    marker = b"a" * 32
    identity = hashlib.sha256(marker).hexdigest()
    adapter.observed_state_id = identity
    private = {"schema": 1, "entries": [{"content": "PRIVATE-fixture"}]}
    monkeypatch.setattr(adapter, "_rpc", lambda *a: {"draining": True, "active_work": 0,
                                                    "release_state": {"state_id": identity}})
    monkeypatch.setattr(adapter, "snapshot", lambda: deepcopy(private))
    monkeypatch.setattr(adapter, "configuration", lambda: {"settings": {"secret": "PRIVATE-config"}})
    stored = {}
    def request(method, url, **kwargs):
        if url.endswith(".image-library-release-state"):
            return 200, {}, marker
        assert "/rollback-backups/" in url
        if method == "PUT":
            assert kwargs["headers"]["If-None-Match"] == "*"
            stored["value"] = kwargs["data"]
            return 201, {}, b""
        return 200, {}, stored["value"]
    adapter.transport.request = request
    assert adapter.freeze_state() == private
    recovered = json.loads(gzip.decompress(stored["value"]))
    assert recovered == {"state": private, "configuration": adapter.configuration()}
    adapter.frozen_state_id = "b" * 64
    with pytest.raises(azure.AzureIOError, match="mount"):
        adapter._check_sentinel()


@pytest.mark.parametrize("active,draining", [(1, True), (False, True), (0, False)])
def test_backup_requires_actual_idle_drain(adapter, monkeypatch, active, draining):
    monkeypatch.setattr(adapter, "_rpc", lambda *a: {"draining": draining, "active_work": active})
    with pytest.raises(azure.AzureIOError, match="idle drain"):
        adapter.freeze_state()


def test_cleanup_refuses_unowned_control_files(adapter):
    adapter.transport.request = lambda *a, **k: (200, {"etag": '"x"'}, b'{"nonce":"someone-else"}')
    with pytest.raises(azure.AzureIOError, match="changed"):
        adapter.cleanup_channel()
