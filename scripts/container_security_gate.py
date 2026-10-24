#!/usr/bin/env python3
"""Fail-closed, image-bound review gate; never modifies the raw Trivy report.

Inspect Docker save archives without extracting or executing their contents.
Reviewed exceptions are exact package/CVE/version/severity tuples and require
the validated base layers and binary hashes. Every run emits a fresh receipt
bound to the complete image archive and config, not a reusable image-tag waiver.
"""
import argparse
import gzip
import hashlib
import io
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath
import tarfile


class GateError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise GateError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive_identity(path, tracked_paths):
    """Reconstruct final file metadata, honoring OCI whiteouts, with no extraction."""
    files = {}
    with tarfile.open(path, "r:*") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        require(len(manifest) == 1, "Exactly one runtime image is required")
        config_bytes = archive.extractfile(manifest[0]["Config"]).read()
        config = json.loads(config_bytes)
        layers = config["rootfs"]["diff_ids"]
        require(len(layers) == len(manifest[0]["Layers"]), "Layer count mismatch")
        for filename, expected in zip(manifest[0]["Layers"], layers):
            data = archive.extractfile(filename).read()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            elif data[:4] == b"\x28\xb5\x2f\xfd":
                data = subprocess.run(["zstd", "--decompress", "--stdout", "--quiet"],
                                      input=data, capture_output=True, check=True, timeout=60).stdout
            require("sha256:" + sha(data) == expected,
                    f"Layer integrity mismatch: {filename} {data[:4].hex()}")
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as layer:
                members = layer.getmembers()
                # Whiteouts remove lower-layer entries, not same-layer additions.
                for member in members:
                    p = PurePosixPath(member.name)
                    require(not p.is_absolute() and ".." not in p.parts,
                            "Unsafe archive member")
                    name = "/" + str(p)
                    if p.name.startswith(".wh."):
                        victim = str(p.parent / p.name[4:])
                        prefix = "/" + str(p.parent) + "/"
                        if p.name == ".wh..wh..opq":
                            files = {k: v for k, v in files.items() if not k.startswith(prefix)}
                        else:
                            victim = "/" + victim
                            files = {k: v for k, v in files.items()
                                     if k != victim and not k.startswith(victim + "/")}
                for member in members:
                    p = PurePosixPath(member.name)
                    if p.name.startswith(".wh."):
                        continue
                    name = "/" + str(p)
                    info = {"mode": member.mode, "type": member.type.decode("ascii"),
                            "link": member.linkname}
                    if name in tracked_paths and member.isfile():
                        info["sha256"] = sha(layer.extractfile(member).read())
                    files[name] = info
    with open(path, "rb") as stream:
        archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"config_id": "sha256:" + sha(config_bytes), "config": config,
            "files": files, "archive_sha256": archive_sha}


def evaluate(policy, raw, identity, commit, build_id, now=None):
    now = now or datetime.now(timezone.utc)
    require(policy["schema_version"] == 1, "Unsupported policy schema")
    reviewed = datetime.fromisoformat(policy["reviewed_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(policy["expires_at"].replace("Z", "+00:00"))
    require(reviewed.tzinfo is not None and expires.tzinfo is not None, "Timezone required")
    require(reviewed <= now < expires, "Review is expired or not yet valid")
    require(timedelta(0) < expires - reviewed <= timedelta(days=30), "Review exceeds 30 days")
    config = identity["config"]
    require(config["architecture"] == "amd64" and config["os"] == "linux", "Wrong platform")
    require(config["rootfs"]["diff_ids"][:len(policy["base_diff_ids"])] == policy["base_diff_ids"],
            "Unreviewed base image layers")
    labels = config["config"]["Labels"]
    require(labels["org.opencontainers.image.revision"] == commit, "Wrong source commit")
    require(labels["org.opencontainers.image.version"] == build_id, "Wrong build ID")
    require(config["config"]["User"] == "65532:65532", "Non-root identity changed")
    require(raw["SchemaVersion"] == 2 and raw["ArtifactType"] == "container_image", "Not an image scan")
    require(raw["Trivy"]["Version"] == policy["scanner_version"], "Unreviewed scanner version")
    scanned = datetime.fromisoformat(raw["CreatedAt"].replace("Z", "+00:00"))
    require(scanned.tzinfo is not None and timedelta(0) <= now - scanned <= timedelta(hours=24),
            "Scan must be from the past 24 hours")
    require(raw["Metadata"]["ImageID"] == identity["config_id"], "Scan belongs to another image")
    require(raw["Metadata"]["ImageConfig"] == config, "Scanned image config differs")
    results = raw["Results"]
    require(any(r["Class"] == "os-pkgs" and r["Type"] == "debian" for r in results), "OS scan missing")
    require(any(r["Class"] == "lang-pkgs" and r["Type"] == "python-pkg" for r in results), "Python scan missing")
    for path, expected in policy["binary_sha256"].items():
        require(identity["files"].get(path, {}).get("sha256") == expected,
                "Reviewed binary changed or missing: " + path)
    for path, info in identity["files"].items():
        name = PurePosixPath(path).name
        require(not (name in {"mount", "umount", "nsenter"} or name.startswith(("mount.", "libmount.so"))),
                "Excluded vulnerable component present: " + path)
        require(not info["mode"] & 0o6000, "Setuid/setgid file present: " + path)
    allowed = {}
    for row in policy["exceptions"]:
        key = (row["cve"], row["package"], row["version"], row["severity"], row["class"], row["type"])
        require(key not in allowed and row["reason"] in {"vendor_backport", "component_absent"},
                "Invalid or duplicate exception")
        allowed[key] = row
    accepted = []
    seen = set()
    for result in results:
        for finding in result.get("Vulnerabilities") or []:
            if finding["Severity"] not in {"HIGH", "CRITICAL"}:
                continue
            key = (finding["VulnerabilityID"], finding["PkgName"], finding["InstalledVersion"],
                   finding["Severity"], result["Class"], result["Type"])
            require(key in allowed, "Unreviewed HIGH/CRITICAL finding: " + repr(key))
            require(key not in seen, "Duplicate finding needs review: " + repr(key))
            seen.add(key)
            require(not finding.get("FixedVersion"), "A vendor fix is now available; re-review required")
            require(finding.get("Status") == "affected", "Scanner status changed; re-review required")
            accepted.append(allowed[key])
    return {"status": "pass", "evaluated_at": now.isoformat(), "expires_at": policy["expires_at"],
            "image_config_id": identity["config_id"], "archive_sha256": identity["archive_sha256"],
            "base_image": policy["base_image"], "commit": commit, "build_id": build_id,
            "reviewed_findings": accepted, "unreviewed_high_critical": 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["policy", "scan", "archive", "commit", "build-id", "output"]:
        p.add_argument("--" + name, required=True)
    args = p.parse_args()
    try:
        policy_bytes = Path(args.policy).read_bytes()
        raw_bytes = Path(args.scan).read_bytes()
        policy = json.loads(policy_bytes)
        result = evaluate(policy, json.loads(raw_bytes),
                          archive_identity(args.archive, policy["binary_sha256"]),
                          args.commit, args.build_id)
        result.update(policy_sha256=sha(policy_bytes), raw_scan_sha256=sha(raw_bytes))
    except (ValueError, KeyError, TypeError, OSError, tarfile.TarError,
            subprocess.SubprocessError) as exc:
        result = {"status": "fail", "error": str(exc)}
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
