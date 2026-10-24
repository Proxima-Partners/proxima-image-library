from types import SimpleNamespace

import pytest

from scripts import rehearsal_lifecycle as lifecycle
from scripts import rehearsal_runner as runner
from scripts.release_azure_io import AzureIOError


def test_log_reads_are_exact_host_path_and_read_only():
    assert lifecycle.log_read_allowed("GET", lifecycle.LOG_ROOT)
    assert lifecycle.log_read_allowed("GET", lifecycle.LOG_ROOT + "2026_10_24_worker123_docker.log")
    for url in (lifecycle.LOG_ROOT + "../secret", lifecycle.LOG_ROOT + "2026_10_24_worker123_docker.log?x=y",
                lifecycle.LOG_ROOT.replace("-rehearsal", "") + "2026_10_24_worker123_docker.log"):
        assert not lifecycle.log_read_allowed("GET", url)
    assert not lifecycle.log_read_allowed("DELETE", lifecycle.LOG_ROOT)


def test_active_overlap_and_confirmed_termination():
    data = b"2026-10-24T00:00:00 Starting container: abc_pp-image-library-rehearsal_main.\n"
    data += b"2026-10-24T00:00:01 Starting container: def_pp-image-library-rehearsal_main.\n"
    assert len(lifecycle.active_containers(data)) == 2
    data += b"2026-10-24T00:00:02 Deleting container: abc_pp-image-library-rehearsal_main.\n"
    assert len(lifecycle.active_containers(data)) == 2
    data += b"2026-10-24T00:00:03 Container is terminated.\n"
    assert lifecycle.active_containers(data) == {"def_pp-image-library-rehearsal_main"}


def test_ambiguous_logs_fail_closed():
    with pytest.raises(AzureIOError): lifecycle.active_containers(b"Container is terminated.\n")


def test_cold_update_never_puts_before_termination(monkeypatch):
    def fail(*args): raise AzureIOError("not stopped")
    monkeypatch.setattr(lifecycle, "stop", fail)
    monkeypatch.setattr(runner, "update", lambda *args: pytest.fail("No image mutation before termination"))
    with pytest.raises(AzureIOError): runner.cold_update(None, None, {}, "prior", set())


def test_cold_update_order_and_no_retry(monkeypatch):
    events = []
    monkeypatch.setattr(lifecycle, "stop", lambda *args: events.append("stop_confirmed"))
    monkeypatch.setattr(runner, "update", lambda *args: events.append("image_put_once") or {"http_status": 200})
    monkeypatch.setattr(lifecycle, "confirm_stopped", lambda *args: events.append("still_stopped"))
    monkeypatch.setattr(runner, "arm", lambda *args, **kwargs: events.append("start_once"))
    monkeypatch.setattr(runner, "ready", lambda *args, **kwargs: events.append("ready"))
    monkeypatch.setattr(lifecycle, "inventory", lambda *args: {"one"})
    lease = SimpleNamespace(checkpoint=lambda _: None)
    result = runner.cold_update(None, lease, {"registry_image": "new"}, "old", {"new", "old"})
    assert events == ["stop_confirmed", "image_put_once", "still_stopped", "start_once", "ready"]
    assert result["prior_termination_verified"]
