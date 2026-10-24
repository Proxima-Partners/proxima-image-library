"""Real one-shot channel + adapter, synthetic SCM over temporary files only."""
import hashlib
from types import SimpleNamespace

import pytest

from scripts import production_azure_adapter as azure
from src import release_channel as channel
from test_production_azure_adapter import receipt
from test_production_release import FakeAdapter


@pytest.fixture
def connected(tmp_path, monkeypatch):
    for name, value in {"APP_STATE_DIR": str(tmp_path), "APP_READ_ONLY": "false",
                        "TELEMETRY_SLOT": "production", "INGEST_POLLER_ENABLED": "false",
                        "PRODUCTION_RELEASE_RESUME_ENABLED": "true"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(channel, "worker_count", lambda: 1)
    release = dict(receipt(), version="v2.0.0")
    state = dict(state_id="c"*64, boot_id="e"*32, uid=65532, gid=65532)
    runtime = channel.ReleaseChannel(tmp_path, state, release, lambda: 1, clock=lambda: 1000)
    channel.controls.set_drain(True)
    calls, inject = [], {"at": None, "after": False, "error": azure.AzureIOError}
    def request(method, url, **kwargs):
        calls.append((method, url))
        fail = len(calls) == inject["at"]
        if fail and not inject["after"]: raise inject["error"]("unknown SCM result")
        path = runtime.directory / url.rsplit("/", 1)[-1]
        raw = path.read_bytes() if path.exists() else b""
        etag = hashlib.sha256(raw).hexdigest()
        if method == "GET":
            result = (200, {"etag": etag}, raw) if path.exists() else (404, {}, b"")
        elif method == "PUT":
            assert kwargs["headers"] == {"If-None-Match": "*"} and not path.exists()
            path.write_bytes(kwargs["data"])
            runtime.process_once()
            result = (201, {}, b"")
        elif method == "DELETE":
            assert kwargs["headers"] == {"If-Match": etag}
            path.unlink()
            result = (204, {}, b"")
        else: pytest.fail("unexpected method")
        if fail: raise inject["error"]("unknown SCM result")
        assert result[0] in kwargs.get("accepted", (200,))
        return result
    lease = SimpleNamespace(assert_held=lambda: None, checkpoint=lambda phase: None)
    obj = azure.AzureProductionAdapter(SimpleNamespace(request=request), lease,
        azure.VerifiedReceipt(receipt("b", "124-1")), azure.VerifiedReceipt(receipt()), clock=lambda: 1000)
    obj.cleanup_attempted = obj.cleanup_complete = True
    obj.lifecycle = SimpleNamespace(inventory=lambda: {"fresh-runtime"})
    obj._config = lambda slot: ({}, {"PRODUCTION_RELEASE_RESUME_ENABLED": "true"}, {}, {})
    obj.configuration = lambda: {}
    guards = []
    def safe(*args):
        assert channel.controls.draining(), "Frozen-state check forbidden after writes resume"
        guards.append(True)
    obj.assert_recovery_safe = safe
    baseline = FakeAdapter().observe("production")
    baseline.update(commit=release["commit"], build_id=release["build_id"], image=release["registry_image"])
    def observe(slot, *, protocol=1):
        response = obj._rpc(slot, "probe", protocol=protocol)
        return dict(baseline, **response["release_state"], draining=response["draining"],
                    active_work=response["active_work"], read_only=response["read_only"])
    obj.observe = observe
    return obj, runtime, baseline, calls, inject


def test_post_restart_verification_resume_and_clean_channel(connected):
    obj, runtime, baseline, calls, inject = connected
    fresh = obj.prepare_resume(receipt(), baseline, {}, {})
    assert fresh["boot_id"] != baseline["boot_id"] and fresh["draining"]
    result = obj.resume_verified(receipt(), fresh, {}, {})
    assert not result["draining"] and obj.resume_complete
    assert list(runtime.directory.iterdir()) == []
    assert not runtime.process_once()


@pytest.mark.parametrize("field,value", [("boot_id", "d"*32), ("state_id", "f"*64)])
def test_wrong_post_restart_identity_never_resumes(connected, field, value):
    obj, runtime, baseline, calls, inject = connected
    runtime.state[field] = value
    with pytest.raises(azure.AzureIOError): obj.prepare_resume(receipt(), baseline, {}, {})
    assert channel.controls.draining() and not obj.resume_attempted


# Resume and its post-write verification each use nine SCM operations. Pin the
# count in the successful test so new transport boundaries require coverage.
RESUME_BOUNDARIES = 18


@pytest.mark.parametrize("boundary", range(1, RESUME_BOUNDARIES + 1))
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("error", [azure.AzureIOError, KeyboardInterrupt])
def test_every_resume_scm_fault_is_terminal_even_if_write_happened(connected, boundary, after, error):
    obj, runtime, baseline, calls, inject = connected
    fresh = obj.prepare_resume(receipt(), baseline, {}, {})
    calls.clear()
    inject.update(at=boundary, after=after, error=error)
    with pytest.raises(error): obj.resume_verified(receipt(), fresh, {}, {})
    assert len(calls) == boundary and obj.resume_attempted and not obj.resume_complete
    with pytest.raises(azure.AzureIOError, match="no retry"):
        obj.resume_verified(receipt(), fresh, {}, {})
    assert len(calls) == boundary


def test_resume_transport_matrix_boundary_count(connected):
    obj, runtime, baseline, calls, inject = connected
    fresh = obj.prepare_resume(receipt(), baseline, {}, {})
    calls.clear()
    obj.resume_verified(receipt(), fresh, {}, {})
    assert len(calls) == RESUME_BOUNDARIES


def test_old_runtime_without_one_shot_support_fails_without_fallback(connected):
    obj, runtime, baseline, calls, inject = connected
    runtime.process_once = lambda: False
    now = [1000]
    obj.clock = lambda: now[0]
    obj.pause = lambda delay: now.__setitem__(0, now[0] + delay)
    with pytest.raises(azure.AzureIOError, match="deadline"):
        obj.prepare_resume(receipt(), baseline, {}, {})
    assert obj.one_shot_uncertain and not obj.resume_attempted
    assert channel.controls.draining()
    assert sum(method == "PUT" for method, url in calls) == 1
