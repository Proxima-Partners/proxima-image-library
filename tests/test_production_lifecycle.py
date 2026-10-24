from types import SimpleNamespace

import pytest

from scripts import production_lifecycle as lifecycle
from scripts.release_azure_io import AzureIOError


def logs(*lines):
    return "\n".join(f"2026-10-24T00:00:{i:02d} {line}" for i, line in enumerate(lines)).encode()


START = "Starting container: abc_pp-image-library_main."
DELETE = "Deleting container: abc_pp-image-library_main."
END = "Container is terminated."


def test_named_termination_not_delete_submission():
    assert lifecycle.lifecycle_state(logs(START, DELETE))[0] == {"abc_pp-image-library_main"}
    assert lifecycle.lifecycle_state(logs(START, DELETE, END)) == (set(), {"abc_pp-image-library_main"})


@pytest.mark.parametrize("raw", [b"", logs(END), logs(DELETE), logs(START, START),
    logs(START, DELETE, DELETE), logs("Starting container: abc_pp-image-library-rehearsal_main.")])
def test_missing_or_ambiguous_history_fails_closed(raw):
    with pytest.raises(AzureIOError):
        lifecycle.lifecycle_state(raw)


def subject():
    events, now = [], [0]
    io = SimpleNamespace(
        json=lambda *a, **k: {"id": lifecycle.APP_ID, "properties": {"state": "Stopped"}},
        request=lambda method, url, **k: events.append((method, url)))
    lease = SimpleNamespace(assert_held=lambda: events.append("lease"),
                            checkpoint=lambda phase: events.append(phase))
    obj = lifecycle.ProductionLifecycle(io, lease, clock=lambda: now[0],
                                       pause=lambda n: now.__setitem__(0, now[0] + n))
    return obj, events


def test_stop_remembers_old_container_and_confirms_termination(monkeypatch):
    obj, events = subject()
    known = {"abc_pp-image-library_main"}
    monkeypatch.setattr(obj, "inventory", lambda: known)
    monkeypatch.setattr(obj, "confirm_stopped", lambda required: events.append(required))
    obj.stop()
    assert events[-1] == known
    assert sum(isinstance(e, tuple) and e[0] == "POST" for e in events) == 1


def test_stopped_arm_without_runtime_termination_times_out(monkeypatch):
    obj, events = subject()
    monkeypatch.setattr(obj, "inventory", lambda required=(): {"old"})
    with pytest.raises(AzureIOError, match="termination unconfirmed"):
        obj.start()
    assert not any(isinstance(e, tuple) for e in events)


def test_lease_loss_prevents_stop(monkeypatch):
    obj, events = subject()
    def lost(): raise AzureIOError("lost lease")
    obj.lease.assert_held = lost
    monkeypatch.setattr(obj, "inventory", lambda: pytest.fail("no read after loss"))
    with pytest.raises(AzureIOError): obj.stop()
    assert events == []


def test_foreign_resource_never_starts(monkeypatch):
    obj, events = subject()
    obj.transport.json = lambda *a, **k: {"id": lifecycle.APP_ID + "-other"}
    with pytest.raises(AzureIOError, match="target"): obj.start()
    assert not any(isinstance(e, tuple) for e in events)
