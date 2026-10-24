"""Authenticated, read-only retrieval of an exact reviewed GitHub build.

No Azure calls, archive extraction, image execution or deployment. The expected
commit/digest must come from the reviewed release decision, not an untrusted PR.
Only the historical reviewed pilot builder is trusted initially; admitting a new
production builder requires a reviewed policy change, not a CLI override.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
import re
import stat
import subprocess
import time
from urllib.parse import urlsplit
import zipfile

import requests

from scripts.pilot_release_manifest import bind
from scripts.production_azure_adapter import verify_receipt_provenance
from scripts.production_release import IMAGE_PATTERN, StopRelease

REPO = "Proxima-Partners/proxima-image-library"
REPO_ID = 1198181428
API = "https://api.github.com/repos/" + REPO
WORKFLOW = ".github/workflows/container-pilot.yml"
WORKFLOW_ID = 393659192
WORKFLOW_SHA256 = "0073793e15d0d09bf09cc4ecfb9e1a8b580f02a0bacaa9d1edacbf7067ed2e8a"
MAX_ARCHIVE = 16 * 1024 * 1024
FILES = {"release.json", "security-gate.json", "registry-manifest.json", "vulnerabilities.json",
         "sbom.cdx.json", "image.json", "smoke.json", "release-channel-smoke.json", "raw-scan-exit-code.txt"}


def require(condition):
    if not condition:
        raise StopRelease("Release artifact verification failed; no deployment permitted")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


class GitHubReads:
    def __init__(self, token, *, session=None, clock=time.monotonic):
        require(isinstance(token, str) and bool(token) and not any(c.isspace() for c in token))
        self.token, self.session = token, session or requests.Session()
        self.session.trust_env = False
        self.clock, self.deadline, self.calls = clock, clock() + 120, 0

    def get(self, url, *, download=False, redirect=False, limit=2 * 1024 * 1024):
        p = urlsplit(url)
        safe = (p.scheme == "https" and p.port in (None, 443) and not p.username and not p.fragment
                and not any(ord(c) < 32 for c in url))
        if download:
            safe = safe and any((p.hostname or "").endswith(s) for s in (".blob.core.windows.net", ".githubusercontent.com"))
        else:
            safe = safe and url.startswith(API + "/") and ".." not in p.path.split("/")
        require(safe and self.calls < 12 and self.clock() < self.deadline)
        headers = {} if download else {"Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}
        self.calls += 1
        try:
            self.session.cookies.clear()
            with self.session.get(url, headers=headers, stream=True, allow_redirects=False,
                                  timeout=min(15, self.deadline - self.clock())) as response:
                if redirect:
                    require(response.status_code == 302)
                    return response.headers.get("Location", "")
                require(response.status_code == 200)
                value = bytearray()
                for chunk in response.iter_content(65536):
                    require(self.clock() < self.deadline and len(value) + len(chunk) <= limit)
                    value.extend(chunk)
                return bytes(value)
        except Exception:
            raise StopRelease("GitHub evidence unavailable; credentials and response withheld") from None

    def json(self, path):
        return parse_json(self.get(API + path))

    def archive(self, artifact_id):
        require(type(artifact_id) is int and artifact_id > 0)
        target = self.get(f"{API}/actions/artifacts/{artifact_id}/zip", redirect=True)
        # GitHub bearer token never follows the signed storage redirect.
        return self.get(target, download=True, limit=MAX_ARCHIVE)


def unpack(raw, artifact):
    """Inspect bounded ZIP members in memory; never extract paths onto disk."""
    require(type(artifact["size_in_bytes"]) is int and 0 < len(raw) == artifact["size_in_bytes"] <= MAX_ARCHIVE)
    require(artifact["digest"] == "sha256:" + sha(raw))
    result, total = {}, 0
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        require(len(archive.infolist()) == len(FILES))
        for info in archive.infolist():
            require(info.filename in FILES and info.filename not in result and not info.is_dir()
                    and not info.flag_bits & 1 and not stat.S_ISLNK(info.external_attr >> 16)
                    and 0 < info.file_size <= MAX_ARCHIVE)
            total += info.file_size
            require(total <= 32 * 1024 * 1024)
            value = archive.read(info)
            require(len(value) == info.file_size)
            result[info.filename] = value
    require(set(result) == FILES)
    return result


def verify_bundle(files, run, expected_image, *, policy_bytes):
    release = parse_json(files["release.json"])
    gate = parse_json(files["security-gate.json"])
    manifest = files["registry-manifest.json"].rstrip(b"\n")
    require(release == bind(expected_image, gate, manifest))
    require(gate["policy_sha256"] == sha(policy_bytes))
    policy = parse_json(policy_bytes)
    require(gate["expires_at"] == policy["expires_at"])
    require(gate["raw_scan_sha256"] == sha(files["vulnerabilities.json"]))
    scan = parse_json(files["vulnerabilities.json"])
    image = parse_json(files["image.json"])
    config = scan["Metadata"]["ImageConfig"]
    build = f"{run['id']}-{run['run_attempt']}"
    require(image["Id"] == scan["Metadata"]["ImageID"] == gate["image_config_id"])
    require(image["Architecture"] == config["architecture"] == "amd64" and image["Os"] == config["os"] == "linux")
    require(image["Config"]["User"] == config["config"]["User"] == "65532:65532")
    require(image["RootFS"]["Layers"] == config["rootfs"]["diff_ids"])
    for labels in (image["Config"]["Labels"], config["config"]["Labels"]):
        require(labels["org.opencontainers.image.revision"] == run["head_sha"]
                and labels["org.opencontainers.image.version"] == build)
    require(files["raw-scan-exit-code.txt"].strip() in {b"0", b"42"})
    require(scan["Trivy"]["Version"] == policy["scanner_version"])
    require({(r["Class"], r["Type"]) for r in scan["Results"]} >= {("os-pkgs", "debian"), ("lang-pkgs", "python-pkg")})
    sbom = parse_json(files["sbom.cdx.json"])
    require(sbom["bomFormat"] == "CycloneDX" and bool(sbom["components"]))
    props = sbom["metadata"]["component"]["properties"]
    require([p["value"] for p in props if p["name"] == "aquasecurity:trivy:ImageID"] == [gate["image_config_id"]])
    smoke, channel = parse_json(files["smoke.json"]), parse_json(files["release-channel-smoke.json"])
    for observation in (smoke["first"], smoke["restart"]):
        require(observation["commit"] == run["head_sha"] and observation["build_id"] == build
                and observation["status"] == "ready" and observation["version"] == "v2.0.0")
        require(observation["pilot_state"]["uid"] == observation["pilot_state"]["gid"] == 65532)
    require(smoke["first"]["pilot_state"]["state_id"] == smoke["restart"]["pilot_state"]["state_id"]
            and smoke["first"]["pilot_state"]["boot_id"] != smoke["restart"]["pilot_state"]["boot_id"])
    require(smoke["network"] == channel["network"] == "none" and smoke["shutdown_exit"] == channel["shutdown_exit"] == 0)
    require(smoke["shellless"] is True and smoke["persistent_state"] is True and channel["status"] == "passed")
    require(channel["build_id"] == build and channel["workers"] == 1
            and all(channel[k] is True for k in ("drain_survived_restart", "mount_preserved", "fresh_boot")))
    return verify_receipt_provenance(release, run, artifact_name="pilot-build-" + build)


def load_receipt(api, run_id, attempt, expected_commit, expected_image, *, policy_bytes):
    """Authenticated GitHub evidence, not caller-supplied run metadata/ZIP files."""
    try:
        require(type(run_id) is int and run_id > 0 and type(attempt) is int and attempt > 0)
        require(bool(re.fullmatch(r"[a-f0-9]{40}", expected_commit)) and bool(re.fullmatch(IMAGE_PATTERN, expected_image)))
        run = api.json(f"/actions/runs/{run_id}")
        require(run["id"] == run_id and run["run_attempt"] == attempt and run["head_sha"] == expected_commit
                and run["repository"]["id"] == run["head_repository"]["id"] == REPO_ID
                and run["repository"]["full_name"] == REPO and run["head_branch"] == "perf/container-pilot"
                and run["path"] == WORKFLOW and run["workflow_id"] == WORKFLOW_ID
                and run["event"] in {"push", "workflow_dispatch"}
                and run["status"] == "completed" and run["conclusion"] == "success")
        source = api.json(f"/contents/{WORKFLOW}?ref={expected_commit}")
        require(source["encoding"] == "base64" and source["path"] == WORKFLOW)
        require(sha(base64.b64decode(source["content"])) == WORKFLOW_SHA256)
        jobs = api.json(f"/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
        require(jobs["total_count"] == len(jobs["jobs"]) <= 100)
        build_jobs = [j for j in jobs["jobs"] if j["name"] == "build"]
        require(len(build_jobs) == 1 and build_jobs[0]["conclusion"] == "success")
        for name in ("Build once, test, smoke, inventory and gate exact image", "Publish validated image and bind registry digest to scan", "Retain all evidence"):
            steps = [s for s in build_jobs[0]["steps"] if s["name"] == name]
            require(len(steps) == 1 and steps[0]["conclusion"] == "success")
        listing = api.json(f"/actions/runs/{run_id}/artifacts?per_page=100")
        require(listing["total_count"] == len(listing["artifacts"]) <= 100)
        found = [a for a in listing["artifacts"] if a["name"] == f"pilot-build-{run_id}-{attempt}"]
        require(len(found) == 1)
        artifact = found[0]
        require(artifact["expired"] is False and artifact["workflow_run"] == {
            "id": run_id, "repository_id": REPO_ID, "head_repository_id": REPO_ID,
            "head_branch": "perf/container-pilot", "head_sha": expected_commit})
        expiry = datetime.fromisoformat(artifact["expires_at"].replace("Z", "+00:00"))
        require(expiry.tzinfo is not None and expiry > datetime.now(timezone.utc))
        files = unpack(api.archive(artifact["id"]), artifact)
        receipt = verify_bundle(files, run, expected_image, policy_bytes=policy_bytes)
        # Reject a rerun/deletion/replacement that occurred while downloading.
        current = api.json(f"/actions/runs/{run_id}")
        require(all(current[k] == run[k] for k in ("id", "run_attempt", "head_sha", "status", "conclusion")))
        require(api.json(f"/actions/artifacts/{artifact['id']}") == artifact)
        receipt["authenticated_artifact"] = {"id": artifact["id"], "digest": artifact["digest"],
            "run_id": run_id, "attempt": attempt, "workflow_sha256": WORKFLOW_SHA256}
        return receipt
    except Exception:
        raise StopRelease("Exact GitHub build evidence could not be verified; no deployment permitted") from None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=int, required=True)
    p.add_argument("--attempt", type=int, required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--image", required=True)
    args = p.parse_args()
    api = None
    try:
        token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
        if not token:
            result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"], capture_output=True, text=True, timeout=20)
            require(result.returncode == 0)
            token = result.stdout.strip()
        api = GitHubReads(token)
        from pathlib import Path
        policy = Path(__file__).resolve().parents[1] / "security" / "container-review.json"
        receipt = load_receipt(api, args.run, args.attempt, args.commit, args.image, policy_bytes=policy.read_bytes())
        print(json.dumps({"status": "verified", "commit": receipt["commit"], "build_id": receipt["build_id"],
            "image": receipt["registry_image"], "artifact": receipt["authenticated_artifact"], "deployment_performed": False}))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "reason": "unverified_build_evidence", "deployment_performed": False}))
        return 1
    finally:
        if api is not None:
            api.session.close()


if __name__ == "__main__":
    raise SystemExit(main())
