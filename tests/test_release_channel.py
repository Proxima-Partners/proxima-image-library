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


@pytest.mark.parametrize("updates", [
    {"protocol": True}, {"protocol": 2}, {"expires": True}, {"expires": 1000},
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
