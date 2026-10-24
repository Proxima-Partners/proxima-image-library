import threading

import pytest

from src import deployment_controls as controls


@pytest.fixture(autouse=True)
def isolated_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("APP_READ_ONLY", "false")
    monkeypatch.delenv("INGEST_POLLER_ENABLED", raising=False)
    monkeypatch.delenv("INGEST_OWNER_HOSTNAME", raising=False)
    monkeypatch.delenv("PILOT_STATE_PROBE_ENABLED", raising=False)
    monkeypatch.delenv("PRODUCTION_RELEASE_CONTROL_ENABLED", raising=False)
    assert controls.snapshot()["active_work"] == 0
    yield
    assert controls.snapshot()["active_work"] == 0


@pytest.mark.parametrize("value", ["true", "yes", "1", "", "flase"])
def test_read_only_fails_closed(monkeypatch, value):
    monkeypatch.setenv("APP_READ_ONLY", value)
    with pytest.raises(controls.WritesDisabled):
        controls.Work()


def test_drain_refuses_new_work_but_allows_admitted_work_to_finish():
    with controls.Work():
        assert controls.set_drain(True)["active_work"] == 1
        with pytest.raises(controls.WritesDisabled):
            controls.Work()
        with controls.Work(admitted=True):
            assert controls.snapshot()["active_work"] == 2
    assert controls.snapshot() == {"read_only": False, "draining": True, "active_work": 0}
    assert controls.drain_path().is_file()
    assert controls.set_drain(False)["draining"] is False


def test_background_work_remains_counted_after_request_finishes():
    finish = threading.Event()
    thread = controls.WorkThread(target=lambda: finish.wait(5), daemon=True)
    try:
        with controls.Work():
            thread.start()
            controls.set_drain(True)
        assert controls.snapshot()["active_work"] == 1
        with pytest.raises(RuntimeError, match="only be started once"):
            thread.start()
        assert controls.snapshot()["active_work"] == 1
    finally:
        finish.set()
        thread.join(5)
    assert not thread.is_alive()


def test_thread_start_failure_releases_ticket(monkeypatch):
    def fail(_self):
        raise RuntimeError("cannot start")
    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(RuntimeError, match="cannot start"):
        controls.WorkThread(target=lambda: None).start()
    assert controls.snapshot()["active_work"] == 0


def test_poller_requires_explicit_single_host_ownership(monkeypatch):
    monkeypatch.setenv("WEBSITE_HOSTNAME", "pilot.azurewebsites.net")
    assert not controls.poller_enabled()
    monkeypatch.setenv("INGEST_POLLER_ENABLED", "true")
    assert not controls.poller_enabled()
    monkeypatch.setenv("INGEST_OWNER_HOSTNAME", "production.azurewebsites.net")
    assert not controls.poller_enabled()
    monkeypatch.setenv("INGEST_OWNER_HOSTNAME", "pilot.azurewebsites.net")
    assert controls.poller_enabled()
    monkeypatch.setenv("APP_READ_ONLY", "true")
    assert not controls.poller_enabled()


def test_state_directory_probe_and_paths(monkeypatch, tmp_path):
    controls.verify_state_directory()
    assert list(tmp_path.iterdir()) == []
    assert controls.state_path("state.json", "fallback.json") == tmp_path / "state.json"
    for invalid in ["relative/path", str(tmp_path / "missing")]:
        monkeypatch.setenv("APP_STATE_DIR", invalid)
        with pytest.raises(RuntimeError, match="existing absolute"):
            controls.verify_state_directory()


def test_pilot_sentinel_persists_and_reports_fresh_boot(monkeypatch, tmp_path):
    monkeypatch.setenv('APP_READ_ONLY', 'true')
    monkeypatch.setenv('PILOT_STATE_PROBE_ENABLED', 'true')
    first = controls.verify_state_directory()
    second = controls.verify_state_directory()
    assert first['state_id'] == second['state_id']
    assert first['boot_id'] != second['boot_id']
    assert len(first['state_id']) == 64
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize('key,value', [('APP_READ_ONLY', 'false'), ('INGEST_POLLER_ENABLED', 'true'), ('INGEST_POLLER_ENABLED', 'typo')])
def test_pilot_sentinel_requires_safe_mode(monkeypatch, tmp_path, key, value):
    monkeypatch.setenv('APP_READ_ONLY', 'true')
    monkeypatch.setenv('PILOT_STATE_PROBE_ENABLED', 'true')
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match='requires read-only'):
        controls.verify_state_directory()
    assert list(tmp_path.iterdir()) == []


def test_pilot_sentinel_never_replaces_invalid_existing_file(monkeypatch, tmp_path):
    monkeypatch.setenv('APP_READ_ONLY', 'true')
    monkeypatch.setenv('PILOT_STATE_PROBE_ENABLED', 'true')
    marker = tmp_path / '.image-library-pilot-state'
    marker.write_bytes(b'existing-data')
    with pytest.raises(RuntimeError, match='Invalid pilot'):
        controls.verify_state_directory()
    assert marker.read_bytes() == b'existing-data'


def test_pilot_sentinel_does_not_follow_symlinks(monkeypatch, tmp_path):
    monkeypatch.setenv('APP_READ_ONLY', 'true')
    monkeypatch.setenv('PILOT_STATE_PROBE_ENABLED', 'true')
    target = tmp_path / 'application-data'
    target.write_bytes(b'protected')
    (tmp_path / '.image-library-pilot-state').symlink_to(target)
    with pytest.raises(OSError): controls.verify_state_directory()
    assert target.read_bytes() == b'protected'


def test_production_identity_opt_in_persists_separately_without_pilot_bypass(monkeypatch, tmp_path):
    assert controls.verify_release_state() is None
    monkeypatch.setenv("PRODUCTION_RELEASE_CONTROL_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_SLOT", "production")
    first = controls.verify_release_state()
    second = controls.verify_release_state()
    assert first["state_id"] == second["state_id"]
    assert first["boot_id"] != second["boot_id"]
    assert not (tmp_path / ".image-library-pilot-state").exists()
    monkeypatch.setenv("PILOT_STATE_PROBE_ENABLED", "true")
    with pytest.raises(RuntimeError, match="cannot use the pilot"):
        controls.verify_release_state()
    with pytest.raises(RuntimeError, match="requires read-only"):
        controls.verify_state_directory()


@pytest.mark.parametrize("key,value", [("APP_STATE_DIR", "relative"), ("TELEMETRY_SLOT", "private-host"),
    ("PRODUCTION_RELEASE_CONTROL_ENABLED", "typo"), ("PILOT_STATE_PROBE_ENABLED", "typo")])
def test_production_state_requires_explicit_valid_configuration(monkeypatch, key, value):
    monkeypatch.setenv("PRODUCTION_RELEASE_CONTROL_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_SLOT", "production")
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        controls.verify_release_state()


@pytest.mark.parametrize("class_name,method", [
    ("SharePointClient", "upload_file"),
    ("SharePointClient", "delete_file"),
    ("SharePointClient", "_upload_session"),
    ("SharePointListClient", "create_record"),
    ("SharePointListClient", "update_record"),
    ("SharePointListClient", "patch_fields"),
    ("SharePointListClient", "bulk_patch_fields"),
    ("SharePointListClient", "bulk_delete_records"),
    ("SharePointListClient", "delete_records"),
    ("SharePointListClient", "delete_all_records"),
])
def test_graph_mutations_rejected_before_client_or_network(monkeypatch, class_name, method):
    from src.sharepoint_client import SharePointClient
    from src.sharepoint_list_client import SharePointListClient
    monkeypatch.setenv("APP_READ_ONLY", "true")
    cls = {"SharePointClient": SharePointClient, "SharePointListClient": SharePointListClient}[class_name]
    # No constructor, arguments, token acquisition or network is necessary.
    with pytest.raises(controls.WritesDisabled):
        getattr(cls, method)(object())
