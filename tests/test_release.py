import io
import json
from zipfile import ZipFile

import pytest

from scripts import package_release, verify_release
from src.release import release_info

SHA = "a" * 40


def test_release_identity_comes_from_artifact_without_git(tmp_path, monkeypatch):
    (tmp_path / "build_info.json").write_text(json.dumps({"commit": SHA}))
    monkeypatch.setattr("src.release.subprocess.check_output", lambda *a, **k: pytest.fail("Git called"))
    assert release_info(tmp_path)["commit"] == SHA


def test_invalid_release_identity_fails_closed(tmp_path):
    (tmp_path / "build_info.json").write_text('{"commit": "untrusted-release"}')
    assert release_info(tmp_path)["commit"] == "unknown"


def test_package_excludes_secrets_test_data_and_vendors(tmp_path, monkeypatch):
    tracked = package_release.REQUIRED | {
        ".env", ".github/workflows/test.yml", "test_data/local_table.json",
        ".python_packages/secret.py", "src/__pycache__/app.pyc",
        "src/.env", "tests/test_app.py", "src/release.py",
    }
    for name in tracked:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setattr(package_release.subprocess, "check_output", lambda *a, **k: "\0".join(tracked).encode())
    output = tmp_path / "release.zip"
    package_release.package_release(output, root=tmp_path, commit=SHA)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == package_release.REQUIRED | {"src/release.py", "build_info.json"}
        assert json.loads(archive.read("build_info.json"))["commit"] == SHA


def test_package_rejects_missing_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release.subprocess, "check_output", lambda *a, **k: b"src/app.py\0")
    with pytest.raises(ValueError, match="Missing required"):
        package_release.package_release(tmp_path / "release.zip", root=tmp_path, commit=SHA)


@pytest.mark.parametrize("body,ok", [
    ({"commit": SHA, "status": "ready"}, True),
    ({"commit": "b" * 40, "status": "ready"}, False),
    ({"commit": SHA, "status": "starting"}, False),
    ({"status": "ok"}, False),
    ([], False),
])
def test_verification_requires_expected_ready_release(monkeypatch, body, ok):
    response = io.BytesIO(json.dumps(body).encode())
    response.status = 200
    monkeypatch.setattr(verify_release, "urlopen", lambda *a, **k: response)
    assert verify_release.check_release("https://example.org", SHA) is ok


def test_readiness_no_upstream_calls_and_cached_identity(monkeypatch):
    import src.app as module
    monkeypatch.setattr(module, "get_client", lambda: pytest.fail("Graph called"))
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **k: pytest.fail("Git called"))
    with module.app.test_client() as client:
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json["status"] == "ready"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json["commit"] == client.get("/api/version").json["commit"]
        monkeypatch.setattr(module, "_READY", False)
        assert client.get("/readyz").status_code == 503


@pytest.mark.parametrize("telemetry,ok", [(True, True), (False, False), (None, False), ("true", False)])
def test_release_gate_requires_initialized_tracing_when_requested(monkeypatch, telemetry, ok):
    response = io.BytesIO(json.dumps({"commit": SHA, "status": "ready", "telemetry": telemetry}).encode())
    response.status = 200
    monkeypatch.setattr(verify_release, "urlopen", lambda *a, **k: response)
    assert verify_release.check_release("https://example.org", SHA, require_telemetry=True) is ok
