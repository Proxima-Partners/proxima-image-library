import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import stat
from types import SimpleNamespace
import zipfile

import pytest

from scripts import release_artifacts as artifacts


def encode(value): return json.dumps(value).encode()


def fixture(monkeypatch):
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    policy = encode({"expires_at": expiry, "scanner_version": "fixture"})
    source = b"reviewed-fixture-workflow"
    monkeypatch.setattr(artifacts, "WORKFLOW_SHA256", artifacts.sha(source))
    run = {"id": 100, "run_attempt": 1, "head_sha": "a" * 40, "head_branch": "perf/container-pilot",
        "path": artifacts.WORKFLOW, "workflow_id": artifacts.WORKFLOW_ID, "event": "push",
        "status": "completed", "conclusion": "success", "repository": {"id": artifacts.REPO_ID, "full_name": artifacts.REPO},
        "head_repository": {"id": artifacts.REPO_ID}}
    config_id = "sha256:" + "b" * 64
    labels = {"org.opencontainers.image.revision": run["head_sha"], "org.opencontainers.image.version": "100-1"}
    config = {"architecture": "amd64", "os": "linux", "config": {"User": "65532:65532", "Labels": labels}, "rootfs": {"diff_ids": []}}
    scan = encode({"Metadata": {"ImageID": config_id, "ImageConfig": config}, "Trivy": {"Version": "fixture"},
                   "Results": [{"Class": "os-pkgs", "Type": "debian"}, {"Class": "lang-pkgs", "Type": "python-pkg"}]})
    gate = {"status": "pass", "expires_at": expiry, "image_config_id": config_id, "policy_sha256": artifacts.sha(policy),
            "raw_scan_sha256": artifacts.sha(scan), "commit": run["head_sha"], "build_id": "100-1", "unreviewed_high_critical": 0}
    manifest = encode({"config": {"digest": config_id}})
    image = "proximaimagelibrary.azurecr.io/image-library@sha256:" + artifacts.sha(manifest)
    smoke = {"commit": run["head_sha"], "build_id": "100-1", "status": "ready", "version": "v2.0.0",
             "pilot_state": {"uid": 65532, "gid": 65532, "state_id": "c" * 64, "boot_id": "d" * 32}}
    restart = deepcopy(smoke); restart["pilot_state"]["boot_id"] = "e" * 32
    files = {"release.json": encode(artifacts.bind(image, gate, manifest)), "security-gate.json": encode(gate),
        "registry-manifest.json": manifest, "vulnerabilities.json": scan,
        "image.json": encode({"Id": config_id, "Architecture": "amd64", "Os": "linux", "Config": config["config"], "RootFS": {"Layers": []}}),
        "sbom.cdx.json": encode({"bomFormat": "CycloneDX", "components": [{"name": "fixture"}], "metadata": {"component": {
            "properties": [{"name": "aquasecurity:trivy:ImageID", "value": config_id}]}}}),
        "smoke.json": encode({"first": smoke, "restart": restart, "network": "none", "shutdown_exit": 0, "shellless": True, "persistent_state": True}),
        "release-channel-smoke.json": encode({"network": "none", "shutdown_exit": 0, "status": "passed", "build_id": "100-1",
            "workers": 1, "drain_survived_restart": True, "mount_preserved": True, "fresh_boot": True}),
        "raw-scan-exit-code.txt": b"42\n"}
    jobs = {"total_count": 1, "jobs": [{"name": "build", "conclusion": "success", "steps": [
        {"name": name, "conclusion": "success"} for name in ("Build once, test, smoke, inventory and gate exact image",
        "Publish validated image and bind registry digest to scan", "Retain all evidence")]}]}
    artifact = {"id": 5, "name": "pilot-build-100-1", "expired": False, "expires_at": expiry,
        "workflow_run": {"id": 100, "repository_id": artifacts.REPO_ID, "head_repository_id": artifacts.REPO_ID,
                         "head_branch": run["head_branch"], "head_sha": run["head_sha"]}}
    state = SimpleNamespace(run=run, policy=policy, source=source, image=image, files=files, jobs=jobs, artifact=artifact, calls=[])
    def repack():
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, value in state.files.items(): archive.writestr(name, value)
        state.raw = output.getvalue()
        artifact.update(size_in_bytes=len(state.raw), digest="sha256:" + artifacts.sha(state.raw))
    state.repack = repack; repack()
    def read(path):
        state.calls.append(path)
        if path == "/actions/runs/100": return deepcopy(state.run)
        if path.startswith("/contents/"): return {"path": artifacts.WORKFLOW, "encoding": "base64", "content": base64.b64encode(state.source).decode()}
        if path.endswith("jobs?per_page=100"): return deepcopy(state.jobs)
        if path.endswith("artifacts?per_page=100"): return {"total_count": 1, "artifacts": [deepcopy(state.artifact)]}
        if path == "/actions/artifacts/5": return deepcopy(state.artifact)
        pytest.fail("Unexpected endpoint")
    state.api = SimpleNamespace(json=read, archive=lambda identity: state.raw)
    return state


def load(state):
    return artifacts.load_receipt(state.api, 100, 1, "a" * 40, state.image, policy_bytes=state.policy)


def test_exact_authenticated_bundle_binds_all_evidence(monkeypatch):
    state = fixture(monkeypatch)
    result = load(state)
    assert result["registry_image"] == state.image
    assert result["authenticated_artifact"]["digest"] == state.artifact["digest"]
    assert state.calls.count("/actions/runs/100") == 2


@pytest.mark.parametrize("key,value", [("run_attempt", 2), ("head_sha", "f" * 40), ("conclusion", "failure"),
    ("event", "pull_request"), ("head_branch", "untrusted"), ("workflow_id", 1), ("status", "in_progress"),
    ("head_repository", {"id": 9})])
def test_untrusted_run_rejected_before_download(monkeypatch, key, value):
    state = fixture(monkeypatch); state.run[key] = value
    state.api.archive = lambda _: pytest.fail("must not download")
    with pytest.raises(artifacts.StopRelease): load(state)


def test_workflow_code_change_and_skipped_build_gate_rejected(monkeypatch):
    state = fixture(monkeypatch); state.source += b" unreviewed"
    with pytest.raises(artifacts.StopRelease): load(state)
    state = fixture(monkeypatch); state.jobs["jobs"][0]["steps"][0]["conclusion"] = "skipped"
    with pytest.raises(artifacts.StopRelease): load(state)


@pytest.mark.parametrize("key,value", [("expired", True), ("expires_at", "2020-01-01T00:00:00Z"),
    ("digest", "sha256:" + "0" * 64), ("size_in_bytes", 1), ("name", "other"), ("workflow_run", {})])
def test_artifact_substitution_and_expiry_rejected(monkeypatch, key, value):
    state = fixture(monkeypatch); state.artifact[key] = value
    with pytest.raises(artifacts.StopRelease): load(state)


@pytest.mark.parametrize("filename", sorted(artifacts.FILES))
def test_each_evidence_file_required(monkeypatch, filename):
    state = fixture(monkeypatch); del state.files[filename]; state.repack()
    with pytest.raises(artifacts.StopRelease): load(state)


@pytest.mark.parametrize("filename,key,value", [
    ("security-gate.json", "unreviewed_high_critical", 1), ("vulnerabilities.json", "Metadata", {}),
    ("image.json", "Id", "sha256:" + "0" * 64), ("sbom.cdx.json", "components", []),
    ("smoke.json", "shellless", False), ("release-channel-smoke.json", "workers", 2),
    ("release-channel-smoke.json", "drain_survived_restart", False)])
def test_cross_file_evidence_binding_cannot_be_bypassed(monkeypatch, filename, key, value):
    state = fixture(monkeypatch)
    data = json.loads(state.files[filename]); data[key] = value
    state.files[filename] = encode(data); state.repack()
    with pytest.raises(artifacts.StopRelease): load(state)


def test_run_rerun_during_download_rejected(monkeypatch):
    state = fixture(monkeypatch)
    def download(_): state.run["run_attempt"] = 2; return state.raw
    state.api.archive = download
    with pytest.raises(artifacts.StopRelease): load(state)


def test_duplicate_json_fields_and_zip_traversal_rejected(monkeypatch):
    with pytest.raises(artifacts.StopRelease): artifacts.parse_json(b'{"status":"pass","status":"fail"}')
    state = fixture(monkeypatch)
    state.files["../release.json"] = state.files.pop("release.json"); state.repack()
    with pytest.raises(artifacts.StopRelease): load(state)


def test_archive_symlink_rejected(monkeypatch):
    state = fixture(monkeypatch); output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in state.files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, value)
    raw = output.getvalue()
    state.artifact.update(size_in_bytes=len(raw), digest="sha256:" + artifacts.sha(raw))
    with pytest.raises(artifacts.StopRelease): artifacts.unpack(raw, state.artifact)


def test_authentication_is_not_forwarded_to_archive_storage():
    class Reply:
        def __init__(self, status, headers, raw=b""): self.status_code, self.headers, self.raw = status, headers, raw
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def iter_content(self, _): yield self.raw
    calls, replies = [], [Reply(302, {"Location": "https://fixture.blob.core.windows.net/archive?sig=private"}), Reply(200, {}, b"fixture")]
    def get(url, **kwargs): calls.append((url, kwargs)); return replies.pop(0)
    session = SimpleNamespace(get=get, cookies=SimpleNamespace(clear=lambda: None))
    api = artifacts.GitHubReads("private-token", session=session)
    assert api.archive(5) == b"fixture"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer private-token"
    assert "Authorization" not in calls[1][1]["headers"]
    assert all(call[1]["allow_redirects"] is False for call in calls)
    with pytest.raises(artifacts.StopRelease): api.get("http://127.0.0.1/", download=True)
    assert len(calls) == 2
