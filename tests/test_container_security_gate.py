import copy
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone

import pytest

from scripts.container_security_gate import GateError, archive_identity, evaluate


NOW = datetime(2026, 10, 23, 5, tzinfo=timezone.utc)


@pytest.fixture
def inputs():
    config = {"architecture": "amd64", "os": "linux", "rootfs": {"diff_ids": ["base", "app"]},
              "config": {"User": "65532:65532", "Labels": {
                  "org.opencontainers.image.revision": "commit", "org.opencontainers.image.version": "build"}}}
    policy = {"schema_version": 1, "scanner_version": "0.76.1", "reviewed_at": "2026-10-23T04:00:00Z",
              "expires_at": "2026-11-21T23:59:59Z", "base_image": "base@digest", "base_diff_ids": ["base"],
              "binary_sha256": {"/usr/bin/infocmp": "patched"}, "exceptions": [{
                  "cve": "CVE-2025-69720", "package": "ncurses-bin", "version": "dhi4", "severity": "HIGH",
                  "class": "os-pkgs", "type": "debian", "reason": "vendor_backport"}]}
    raw = {"SchemaVersion": 2, "Trivy": {"Version": "0.76.1"}, "CreatedAt": "2026-10-23T04:01:00Z",
           "ArtifactType": "container_image", "Metadata": {"ImageID": "sha256:config", "ImageConfig": copy.deepcopy(config)},
           "Results": [{"Class": "os-pkgs", "Type": "debian", "Vulnerabilities": [{
               "VulnerabilityID": "CVE-2025-69720", "PkgName": "ncurses-bin", "InstalledVersion": "dhi4",
               "Severity": "HIGH", "Status": "affected"}]}, {"Class": "lang-pkgs", "Type": "python-pkg"}]}
    identity = {"config_id": "sha256:config", "config": config, "archive_sha256": "archive",
                "files": {"/usr/bin/infocmp": {"sha256": "patched", "mode": 0o755}}}
    return policy, raw, identity


def test_scoped_acceptance_retains_findings(inputs):
    result = evaluate(*inputs, "commit", "build", now=NOW)
    assert result["status"] == "pass"
    assert len(result["reviewed_findings"]) == 1
    assert result["archive_sha256"] == "archive"


@pytest.mark.parametrize("change", [
    "expired", "future", "long_review", "wrong_base", "wrong_arch", "wrong_user", "wrong_image",
    "wrong_config", "missing_python", "missing_os", "wrong_binary", "missing_binary", "mount",
    "libmount", "nsenter", "setuid", "new_cve", "new_version", "new_package", "critical",
    "fixed", "status_changed", "duplicate", "python_vulnerability", "stale", "future_scan", "scanner_changed",
])
def test_fail_closed(inputs, change):
    policy, raw, identity = inputs
    finding = raw["Results"][0]["Vulnerabilities"][0]
    if change == "expired": policy["expires_at"] = "2026-10-23T04:59:59Z"
    elif change == "future": policy["reviewed_at"] = "2026-10-23T06:00:00Z"
    elif change == "long_review": policy["expires_at"] = "2027-01-01T00:00:00Z"
    elif change == "wrong_base": identity["config"]["rootfs"]["diff_ids"][0] = "changed"
    elif change == "wrong_arch": identity["config"]["architecture"] = "arm64"
    elif change == "wrong_user": identity["config"]["config"]["User"] = "0"
    elif change == "wrong_image": raw["Metadata"]["ImageID"] = "other"
    elif change == "wrong_config": raw["Metadata"]["ImageConfig"]["os"] = "windows"
    elif change == "missing_python": raw["Results"].pop()
    elif change == "missing_os": raw["Results"].pop(0)
    elif change == "wrong_binary": identity["files"]["/usr/bin/infocmp"]["sha256"] = "old"
    elif change == "missing_binary": identity["files"].clear()
    elif change in {"mount", "nsenter", "libmount"}:
        name = "libmount.so.1" if change == "libmount" else change
        identity["files"]["/custom/" + name] = {"mode": 0o755}
    elif change == "setuid": identity["files"]["/custom/helper"] = {"mode": 0o4755}
    elif change == "new_cve": finding["VulnerabilityID"] = "CVE-2099-9999"
    elif change == "new_version": finding["InstalledVersion"] = "dhi5"
    elif change == "new_package": finding["PkgName"] = "libssl"
    elif change == "critical": finding["Severity"] = "CRITICAL"
    elif change == "fixed": finding["FixedVersion"] = "dhi5"
    elif change == "status_changed": finding["Status"] = "unknown"
    elif change == "duplicate": raw["Results"][0]["Vulnerabilities"].append(copy.deepcopy(finding))
    elif change == "python_vulnerability": raw["Results"][1]["Vulnerabilities"] = [copy.deepcopy(finding)]
    elif change == "stale": raw["CreatedAt"] = "2026-10-21T05:00:00Z"
    elif change == "future_scan": raw["CreatedAt"] = "2026-10-24T05:00:00Z"
    elif change == "scanner_changed": raw["Trivy"]["Version"] = "other"
    with pytest.raises(GateError): evaluate(policy, raw, identity, "commit", "build", now=NOW)


@pytest.mark.parametrize("commit,build", [("other", "build"), ("commit", "other")])
def test_wrong_release_identity(inputs, commit, build):
    with pytest.raises(GateError): evaluate(*inputs, commit, build, now=NOW)


def layer_bytes(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in entries:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return stream.getvalue()


def test_archive_checks_layers_and_applies_whiteouts(tmp_path):
    layers = [layer_bytes([("usr/bin/infocmp", b"old"), ("usr/bin/mount", b"bad")]),
              layer_bytes([("usr/bin/.wh.mount", b""), ("usr/bin/infocmp", b"patched")])]
    config = json.dumps({"rootfs": {"diff_ids": ["sha256:" + hashlib.sha256(b).hexdigest() for b in layers]}}).encode()
    manifest = json.dumps([{"Config": "config.json", "Layers": ["0.tar", "1.tar"]}]).encode()
    image = tmp_path / "runtime.tar"
    image.write_bytes(layer_bytes([("manifest.json", manifest), ("config.json", config),
                                   ("0.tar", layers[0]), ("1.tar", layers[1])]))
    result = archive_identity(image, {"/usr/bin/infocmp"})
    assert "/usr/bin/mount" not in result["files"]
    assert result["files"]["/usr/bin/infocmp"]["sha256"] == hashlib.sha256(b"patched").hexdigest()
    image.write_bytes(layer_bytes([("manifest.json", manifest), ("config.json", config),
                                   ("0.tar", layers[0]), ("1.tar", layer_bytes([("bad", b"tampered")]))]))
    with pytest.raises(GateError, match="integrity"): archive_identity(image, {})
