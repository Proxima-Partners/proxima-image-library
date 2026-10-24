import json
import os
import stat

import pytest

from src import release_channel as channel


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("TELEMETRY_SLOT", "production")
    monkeypatch.setenv("APP_READ_ONLY", "false")
    monkeypatch.setattr(channel, "worker_count", lambda: 1)
    return channel.ReleaseChannel(tmp_path, {"state_id": "a" * 64},
                                  {"version": "v2.0.0"}, lambda: 1, clock=lambda: 1000)


def request(runtime, **updates):
    value = {"protocol": 1, "nonce": "a" * 32, "expires": 1060, "action": "status"}
    value.update(updates)
    (runtime.directory / "request.json").write_text(json.dumps(value))


def response(runtime):
    return json.loads((runtime.directory / "response.json").read_text())


def test_status_is_fresh_private_and_no_catalog_contents(runtime):
    request(runtime)
    assert runtime.process_once()
    result = response(runtime)
    assert result["at"] == 1000 and result["ok"] is True
    assert result["workers"] == 1 and result["slot"] == "production"
    assert result["release_state"] == runtime.state
    assert result["active_work"] == 0 and result["draining"] is False
    assert "sample_records" not in result
    assert stat.S_IMODE((runtime.directory / "response.json").stat().st_mode) == 0o600


def test_state_probe_actual_identity_and_cleanup(runtime):
    request(runtime, action="state_probe")
    assert runtime.process_once()
    result = response(runtime)
    assert result["ok"]
    assert result["state_probe"] == {"uid": os.getuid(), "gid": os.getgid(),
        "file_uid": os.getuid(), "file_gid": os.getgid(), "file_mode": 0o600,
        "read_write_rename": True, "cleanup_verified": True}
    assert not list(runtime.directory.parent.glob(".image-library-state-probe-*"))


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_state_probe_never_adopts_existing_path(runtime, kind):
    path = runtime.directory.parent / (".image-library-state-probe-" + "a"*32)
    if kind == "directory":
        path.mkdir()
        (path / "precious").write_text("keep")
    else:
        path.symlink_to(runtime.directory, target_is_directory=True)
    request(runtime, action="state_probe")
    assert runtime.process_once() and response(runtime)["ok"] is False
    assert path.exists()
    if kind == "directory":
        assert (path / "precious").read_text() == "keep"


def test_state_probe_failure_retains_fixture_and_redacts(runtime, monkeypatch):
    def failed(*args, **kwargs):
        raise OSError("SECRET-fixture")
    monkeypatch.setattr(os, "rename", failed)
    request(runtime, action="state_probe")
    assert runtime.process_once() and response(runtime)["ok"] is False
    assert "SECRET" not in (runtime.directory / "response.json").read_text()
    assert (runtime.directory.parent / (".image-library-state-probe-" + "a"*32) / "original").is_file()


@pytest.mark.parametrize("updates", [
    {"protocol": True}, {"protocol": 3}, {"expires": True}, {"expires": 1000},
    {"expires": 1061}, {"expires": "1060"}, {"nonce": "wrong"}, {"nonce": []},
    {"action": "undrain"}, {"action": "exec"}, {"action": []}, {"extra": 1},
])
def test_invalid_commands_do_not_mutate(runtime, updates):
    request(runtime, **updates)
    assert runtime.process_once() is False
    assert not (runtime.directory / "response.json").exists()
    assert not channel.controls.draining()


@pytest.mark.parametrize("raw", [b"[]", b"null", b"{", b"\xff", b"x" * 4097])
def test_invalid_or_oversized_json(runtime, raw):
    (runtime.directory / "request.json").write_bytes(raw)
    assert runtime.process_once() is False


def test_replays_after_other_request_are_rejected(runtime):
    request(runtime)
    assert runtime.process_once()
    request(runtime, nonce="b" * 32)
    assert runtime.process_once()
    request(runtime)
    assert runtime.process_once() is False
    assert response(runtime)["nonce"] == "b" * 32


def test_drain_is_one_way_and_survives_new_channel(runtime):
    request(runtime, action="drain")
    assert runtime.process_once() and response(runtime)["draining"] is True
    other = channel.ReleaseChannel(runtime.directory.parent, runtime.state, runtime.release, lambda: 0, clock=lambda: 1000)
    request(other, nonce="b" * 32)
    assert other.process_once() and response(other)["draining"] is True


@pytest.mark.parametrize("count", [0, 1, 2, True, None])
def test_probe_is_bounded(runtime, count):
    runtime.read_probe = lambda: count
    request(runtime, action="probe")
    assert runtime.process_once()
    assert response(runtime)["ok"] is (type(count) is int and count in (0, 1))


def test_probe_exception_is_redacted(runtime):
    def fail():
        raise RuntimeError("SECRET-CREDENTIAL")
    runtime.read_probe = fail
    request(runtime, action="probe")
    assert runtime.process_once()
    assert response(runtime)["ok"] is False
    assert "SECRET" not in (runtime.directory / "response.json").read_text()


def test_no_request_or_symlink(runtime, tmp_path):
    assert runtime.process_once() is False
    target = tmp_path / "other"
    target.write_text("{}")
    (runtime.directory / "request.json").symlink_to(target)
    with pytest.raises(OSError):
        runtime.process_once()


def test_control_directory_symlink_rejected(tmp_path):
    (tmp_path / channel.DIRECTORY).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError):
        channel.ReleaseChannel(tmp_path, {}, {}, lambda: 0)


def test_worker_count_needs_real_linux_single_child(monkeypatch):
    monkeypatch.setattr(os, "getppid", lambda: 1)
    monkeypatch.setattr(os, "getpid", lambda: 42)
    monkeypatch.setattr(channel.Path, "read_bytes", lambda self: b"python\x00-m\x00gunicorn\x00")
    monkeypatch.setattr(channel.Path, "read_text", lambda self: "42 ")
    assert channel.worker_count() == 1
    monkeypatch.setattr(channel.Path, "read_text", lambda self: "42 43 ")
    assert channel.worker_count() is None
    monkeypatch.setattr(os, "getppid", lambda: 3)
    assert channel.worker_count() is None


def resume_request(runtime):
    runtime.release.update(commit="b" * 40, build_id="100-1")
    runtime.state.update(boot_id="c" * 32)
    expected = dict(runtime.state, commit=runtime.release["commit"], build_id="100-1")
    request(runtime, action="resume", expected=expected)
    return expected


def test_resume_disabled_by_default_even_with_exact_runtime_binding(runtime, monkeypatch):
    monkeypatch.delenv("PRODUCTION_RELEASE_RESUME_ENABLED", raising=False)
    channel.controls.set_drain(True); resume_request(runtime)
    assert runtime.process_once() and response(runtime)["ok"] is False
    assert channel.controls.draining()


def test_resume_requires_explicit_flag_exact_runtime_idle_and_single_owner(runtime, monkeypatch):
    monkeypatch.setenv("PRODUCTION_RELEASE_RESUME_ENABLED", "true")
    monkeypatch.setenv("INGEST_POLLER_ENABLED", "false")
    channel.controls.set_drain(True); resume_request(runtime)
    assert runtime.process_once() and response(runtime)["ok"] is True
    assert response(runtime)["draining"] is False
    assert runtime.process_once() is False  # no replay


@pytest.mark.parametrize("key,value", [("TELEMETRY_SLOT", "staging"), ("INGEST_POLLER_ENABLED", "true"),
    ("APP_READ_ONLY", "true"), ("PRODUCTION_RELEASE_RESUME_ENABLED", "yes")])
def test_resume_wrong_policy_stays_drained(runtime, monkeypatch, key, value):
    monkeypatch.setenv("PRODUCTION_RELEASE_RESUME_ENABLED", "true")
    monkeypatch.setenv("INGEST_POLLER_ENABLED", "false")
    monkeypatch.setenv(key, value)
    channel.controls.set_drain(True); resume_request(runtime)
    assert runtime.process_once() and response(runtime)["ok"] is False
    assert channel.controls.draining()


def test_resume_rejects_active_work_and_changed_boot(runtime, monkeypatch):
    monkeypatch.setenv("PRODUCTION_RELEASE_RESUME_ENABLED", "true")
    monkeypatch.setenv("INGEST_POLLER_ENABLED", "false")
    with channel.controls.Work():
        channel.controls.set_drain(True); resume_request(runtime)
        assert runtime.process_once() and response(runtime)["ok"] is False
    expected = resume_request(runtime)
    expected["boot_id"] = "d" * 32
    request(runtime, action="resume", expected=expected, nonce="e" * 32)
    assert runtime.process_once() and response(runtime)["ok"] is False
    assert channel.controls.draining()


def test_one_shot_retires_request_before_resume_and_cannot_replay_after_restart(runtime, monkeypatch):
    monkeypatch.setenv("PRODUCTION_RELEASE_RESUME_ENABLED", "true")
    monkeypatch.setenv("INGEST_POLLER_ENABLED", "false")
    channel.controls.set_drain(True)
    expected = resume_request(runtime)
    real_resume = channel.controls.resume_if_idle
    def resume():
        assert not (runtime.directory / "request.json").exists()
        real_resume()
    monkeypatch.setattr(channel.controls, "resume_if_idle", resume)
    request(runtime, protocol=2, action="resume", expected=expected)
    assert runtime.process_once()
    assert response(runtime)["request_retired"] and response(runtime)["ok"]
    assert response(runtime)["draining"] is False
    restarted = channel.ReleaseChannel(runtime.directory.parent, runtime.state, runtime.release, lambda: 1)
    assert not restarted.process_once()


@pytest.mark.parametrize("failure", ["unlink", "fsync"])
def test_one_shot_retirement_failure_never_resumes(runtime, monkeypatch, failure):
    monkeypatch.setenv("PRODUCTION_RELEASE_RESUME_ENABLED", "true")
    monkeypatch.setenv("INGEST_POLLER_ENABLED", "false")
    channel.controls.set_drain(True)
    expected = resume_request(runtime)
    request(runtime, protocol=2, action="resume", expected=expected)
    def fail(*a, **k): raise OSError("retirement uncertain")
    monkeypatch.setattr(channel.os, failure, fail)
    with pytest.raises(OSError): runtime.process_once()
    assert channel.controls.draining()


def test_one_shot_response_loss_after_resume_does_not_reexecute(runtime, monkeypatch):
    monkeypatch.setenv("PRODUCTION_RELEASE_RESUME_ENABLED", "true")
    monkeypatch.setenv("INGEST_POLLER_ENABLED", "false")
    channel.controls.set_drain(True)
    expected = resume_request(runtime)
    request(runtime, protocol=2, action="resume", expected=expected)
    def fail(*a, **k): raise OSError("response uncertain")
    monkeypatch.setattr(channel.os, "replace", fail)
    with pytest.raises(OSError): runtime.process_once()
    assert not channel.controls.draining()
    assert not runtime.process_once()


def test_one_shot_stale_boot_is_retired_without_resuming(runtime, monkeypatch):
    monkeypatch.setenv("PRODUCTION_RELEASE_RESUME_ENABLED", "true")
    monkeypatch.setenv("INGEST_POLLER_ENABLED", "false")
    channel.controls.set_drain(True)
    expected = resume_request(runtime)
    expected["boot_id"] = "d" * 32
    request(runtime, protocol=2, action="resume", expected=expected)
    assert runtime.process_once() and not response(runtime)["ok"]
    assert channel.controls.draining() and not (runtime.directory / "request.json").exists()
