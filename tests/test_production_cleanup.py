"""Fault injection across the real adapter's stopped-cleanup orchestration.

All provider boundaries are synthetic; no Azure calls, credentials or app data.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import production_azure_adapter as azure
from scripts import production_release as controller
from test_production_azure_adapter import receipt
from test_production_release import FakeAdapter, run


def harness(fail_at=None, error=azure.AzureIOError):
    events = []
    state = {"held": False, "released": False}
    def event(name):
        events.append(name)
        if len(events) == fail_at:
            raise error("synthetic-private-detail")
    @contextmanager
    def exclusive(resource):
        state["held"] = True
        yield
        state.update(held=False, released=True)
    lease = SimpleNamespace(exclusive=exclusive,
        assert_held=lambda: event("lease"), checkpoint=lambda phase: event(phase))
    obj = azure.AzureProductionAdapter(SimpleNamespace(), lease,
        azure.VerifiedReceipt(receipt("b", "124-1")), azure.VerifiedReceipt(receipt()))
    obj.assert_recovery_safe = lambda *a: event("protected_state")
    obj._cleanup_identity = lambda slot: (event(slot + ":identity") or
        {"container": {"properties": {"image": receipt()["registry_image"]}}})
    obj.snapshot = lambda slot="production": (event(slot + ":snapshot") or {"stable": True})
    obj._wait_cold_readiness = lambda *a, slot="production": event(slot + ":ready")
    obj._check_public_auth = lambda slot: event(slot + ":auth")
    obj._assert_channel_absent = lambda slot: event(slot + ":absent")
    for slot in ("production", "staging"):
        obj.nonces[slot].add("owned")
        obj.lifecycles[slot] = SimpleNamespace(
            stop=lambda slot=slot: (event(slot + ":stop") or {"old"}),
            start=lambda slot=slot: event(slot + ":start"),
            confirm_stopped=lambda slot=slot: event(slot + ":stopped"),
            inventory=lambda slot=slot: (event(slot + ":inventory") or {"new"}))
    obj.lifecycle = obj.lifecycles["production"]
    files = {}
    def request(method, url, **kwargs):
        slot = "staging" if "-staging." in url else "production"
        event(slot + ":" + method + ":" + url.rsplit("/", 1)[-1])
        if method == "DELETE":
            assert kwargs["headers"] == {"If-Match": '"owned-etag"'}
            files[url] = False
            return 204, {}, b""
        if files.get(url, True):
            return 200, {"etag": '"owned-etag"'}, b'{"nonce":"owned"}'
        return 404, {}, b""
    obj.transport.request = request
    return obj, events, state


def execute(obj):
    with obj.exclusive(azure.APP_ID):
        obj.finalize_held(receipt(), {}, {})


def test_cleanup_both_slots_and_release_only_after_verification():
    obj, events, state = harness()
    execute(obj)
    assert obj.cleanup_complete and state == {"held": False, "released": True}
    for slot in ("production", "staging"):
        assert events.index(slot + ":stop") < events.index(slot + ":DELETE:request.json")
        assert events.index(slot + ":DELETE:response.json") < events.index(slot + ":start")
        assert events.index(slot + ":start") < events.index(slot + ":ready") < events.index(slot + ":absent")
    assert events.index("staging:absent") < events.index("production:stop")


_example, _events, _state = harness()
execute(_example)
BOUNDARY_COUNT = len(_events)


@pytest.mark.parametrize("boundary", range(1, BOUNDARY_COUNT + 1))
@pytest.mark.parametrize("error", [azure.AzureIOError, KeyboardInterrupt])
def test_every_cleanup_boundary_failure_retains_lease_and_prevents_replay(boundary, error):
    obj, events, state = harness(boundary, error)
    with pytest.raises(error): execute(obj)
    assert len(events) == boundary
    assert state == {"held": True, "released": False}
    assert not obj.cleanup_complete
    with pytest.raises(azure.AzureIOError, match="replayed"):
        obj.finalize_held(receipt(), {}, {})
    assert len(events) == boundary


@pytest.mark.parametrize("active", [set(), {"old"}, {"new", "other"}])
def test_restart_requires_one_fresh_runtime(active):
    obj, events, state = harness()
    obj.lifecycles["staging"].inventory = lambda: active
    with pytest.raises(azure.AzureIOError, match="fresh named runtime"): execute(obj)
    assert "production:stop" not in events and state["held"]


@pytest.mark.parametrize("body,headers", [(b'{"nonce":"foreign"}', {"etag": "x"}),
    (b'{"nonce":"owned"}', {}), (b'[]', {"etag": "x"}), (b'not json', {"etag": "x"})])
def test_cleanup_never_deletes_unowned_or_unconditional_files(body, headers):
    obj, events, state = harness()
    calls = []
    def request(method, *a, **k):
        calls.append(method)
        return 200, headers, body
    obj.transport.request = request
    with pytest.raises((azure.AzureIOError, ValueError)): execute(obj)
    assert calls == ["GET"] and state["held"]


@pytest.mark.parametrize("rollback", [False, True])
def test_controller_cleanup_failure_never_records_success_or_retries_image(tmp_path, rollback):
    obj = FakeAdapter()
    if rollback: obj.fault = "confirmed_failure"
    def failed(*a): raise azure.AzureIOError("cleanup uncertain")
    obj.finalize_held = failed
    with pytest.raises(controller.StopRelease): run(obj, tmp_path)
    assert len(obj.updates) == (2 if rollback else 1)
    journal = (tmp_path / "release.jsonl").read_text()
    assert '"phase": "candidate_verified_held"' not in journal
    assert '"phase": "rollback_verified_held"' not in journal
    assert "stopped_reconcile_no_retry" in journal


def test_unconfigured_resume_rejected_before_controller_mutations(tmp_path):
    obj, events, state = harness()
    obj._config = lambda slot: ({}, {}, {}, {})
    with pytest.raises(azure.AzureIOError, match="approved"):
        controller.promote(obj, receipt("b", "124-1"), receipt(), tmp_path / "journal", resume_writes=True)
    assert not events and not (tmp_path / "journal").exists()


def test_missing_finalize_cannot_release_lease():
    obj, events, state = harness()
    with pytest.raises(azure.AzureIOError, match="acceptance missing"):
        with obj.exclusive(azure.APP_ID): pass
    assert state["held"] and not state["released"]


def test_completed_cleanup_seals_channel_and_image_mutations():
    obj, events, state = harness()
    execute(obj)
    with pytest.raises(azure.AzureIOError, match="sealed"):
        obj._rpc("production", "probe")
    with pytest.raises(azure.AzureIOError, match="unresolved"):
        obj.update(receipt()["registry_image"])


@pytest.mark.parametrize("slot", ["production", "staging"])
@pytest.mark.parametrize("field", ["snapshot", "_cleanup_identity"])
def test_state_or_configuration_drift_after_stop_prevents_delete_and_restart(slot, field):
    obj, events, state = harness()
    original = getattr(obj, field)
    def changed(target="production"):
        value = original(target)
        if target == slot and slot + ":stop" in events:
            return dict(value, concurrent_change=True)
        return value
    setattr(obj, field, changed)
    with pytest.raises(azure.AzureIOError, match="state changed"): execute(obj)
    assert slot + ":DELETE:request.json" not in events
    assert slot + ":start" not in events and state["held"]


class FaultControllerAdapter(FakeAdapter):
    """Instrument each policy-to-adapter boundary; no real provider calls."""
    METHODS = {"assert_lease", "observe", "configuration", "drain", "freeze_state",
               "assert_recovery_safe", "update", "verify", "finalize_held"}

    def __init__(self, *, rollback=False, fail_at=None, error=RuntimeError):
        super().__init__()
        self.calls = []
        self.fail_at, self.error = fail_at, error
        if rollback: self.fault = "confirmed_failure"

    def __getattribute__(self, name):
        method = super().__getattribute__(name)
        if name not in FaultControllerAdapter.METHODS:
            return method
        def call(*args, **kwargs):
            self.calls.append(name)
            if len(self.calls) == self.fail_at:
                raise self.error("synthetic-private-detail")
            return method(*args, **kwargs)
        return call


# Count each successful path without disk/network; its methods are the same
# ones exercised through promote() below. Explicit range bounds are checked by
# the success test so a new controller phase cannot silently escape the matrix.
CONTROLLER_BOUNDARIES = {False: 19, True: 26}


@pytest.mark.parametrize("rollback", [False, True])
def test_controller_matrix_covers_all_boundaries(tmp_path, rollback):
    obj = FaultControllerAdapter(rollback=rollback)
    run(obj, tmp_path)
    assert len(obj.calls) == CONTROLLER_BOUNDARIES[rollback], obj.calls


@pytest.mark.parametrize("rollback,boundary", [(rollback, i)
    for rollback, count in CONTROLLER_BOUNDARIES.items() for i in range(1, count + 1)])
@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_controller_failure_matrix_retains_lease_and_stops_at_fault(tmp_path, rollback, boundary, error):
    obj = FaultControllerAdapter(rollback=rollback, fail_at=boundary, error=error)
    with pytest.raises((controller.StopRelease, KeyboardInterrupt)) as caught:
        run(obj, tmp_path)
    assert len(obj.calls) == boundary
    assert obj.held
    assert len(obj.updates) <= (2 if rollback else 1)
    if isinstance(caught.value, controller.StopRelease):
        assert "synthetic-private-detail" not in str(caught.value)
