#!/usr/bin/env python3
"""Offline checks of the EXACT runtime image. No Azure/Graph access or credentials.

Uses a uniquely named disposable Docker volume; removes only that volume and
its own container. Tests mount persistence, auth, identity and graceful SIGTERM.
The writable root filesystem is disabled; network access is disabled entirely.
"""

import argparse
import json
import os
import secrets
import subprocess
import time
import uuid


def docker(*args, **kwargs):
    return subprocess.check_output(["docker", *args], text=True, **kwargs).strip()


PROBE = r'''
import json, os, ssl, stat, sys
from pathlib import Path
from urllib.request import urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from PIL import features
assert os.getuid() == os.getgid() == 65532
assert sys.prefix == "/opt/venv"
assert features.check("webp")
assert ssl.create_default_context().cert_store_stats()["x509_ca"] > 0
for binary in ["sh", "bash", "mount", "nsenter", "apt", "apt-get", "dpkg"]:
    import shutil
    assert shutil.which(binary) is None, binary
for parent in ["/usr/bin", "/usr/sbin", "/bin", "/sbin"]:
    for path in Path(parent).glob("*"):
        assert not path.stat().st_mode & (stat.S_ISUID | stat.S_ISGID), str(path)
assert b"gunicorn" in Path("/proc/1/cmdline").read_bytes()
assert not os.access("/app", os.W_OK)
assert not any(Path(p).exists() for p in ["/app/.env", "/app/.git", "/app/tests", "/app/test_data"])
for module in ["pytest", "pip_audit", "pip"]:
    import importlib.util
    assert importlib.util.find_spec(module) is None
with urlopen("http://127.0.0.1:8080/readyz", timeout=3) as r:
    info = json.load(r)
assert info["status"] == "ready"
assert info["commit"] == os.environ["EXPECTED_COMMIT"]
assert info["build_id"] == os.environ["EXPECTED_BUILD_ID"]
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
try:
    build_opener(NoRedirect).open("http://127.0.0.1:8080/", timeout=3)
    raise AssertionError("Anonymous catalog access allowed")
except HTTPError as e:
    assert e.code == 302 and e.headers["Location"].endswith("/login")
with urlopen("http://127.0.0.1:8080/health", timeout=3) as r:
    assert json.load(r) == {"status": "ok"}
with urlopen("http://127.0.0.1:8080/static/review-badge.js", timeout=3) as r:
    assert "javascript" in r.headers["Content-Type"]
    assert r.read() == Path("/app/static/review-badge.js").read_bytes()
assert b"createReviewBadgePoller" in Path("/app/static/review-badge.js").read_bytes()
print(json.dumps(info))
'''


def smoke(image, commit, build_id):
    name = "image-library-smoke-" + uuid.uuid4().hex[:12]
    volume = name + "-state"
    created = False
    run_env = dict(os.environ, FLASK_SECRET_KEY=secrets.token_hex(32))
    try:
        docker("volume", "create", volume)
        created = True
        docker("run", "--detach", "--platform", "linux/amd64", "--name", name,
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=64m",
               "--mount", f"type=volume,source={volume},target=/home",
               "--env", "FLASK_SECRET_KEY", "--env", "TELEMETRY_ENABLED=false",
               "--env", "PILOT_STATE_PROBE_ENABLED=true",
               "--env", f"EXPECTED_COMMIT={commit}", "--env", f"EXPECTED_BUILD_ID={build_id}",
               image, env=run_env)

        def ready():
            for _ in range(45):
                try:
                    return json.loads(docker("exec", name, "python", "-c", PROBE, stderr=subprocess.DEVNULL))
                except (subprocess.CalledProcessError, json.JSONDecodeError):
                    time.sleep(1)
            raise RuntimeError("Offline runtime smoke check failed")

        first = ready()
        docker("exec", name, "python", "-c",
               "from pathlib import Path; Path('/home/smoke-state').write_text('persisted')")
        docker("stop", "--time", "15", name)
        exit_code = docker("inspect", "--format", "{{.State.ExitCode}}", name)
        if exit_code != "0":
            raise RuntimeError(f"SIGTERM did not shut down cleanly: exit {exit_code}")
        docker("start", name)
        second = ready()
        if first['pilot_state']['state_id'] != second['pilot_state']['state_id']:
            raise RuntimeError('Pilot persistence sentinel changed across restart')
        if first['pilot_state']['boot_id'] == second['pilot_state']['boot_id']:
            raise RuntimeError('Restart did not produce a fresh application boot')
        if second['pilot_state']['uid'] != 65532 or second['pilot_state']['gid'] != 65532:
            raise RuntimeError('Pilot probe did not run as nonroot')
        docker("exec", name, "python", "-c",
               "from pathlib import Path; assert Path('/home/smoke-state').read_text() == 'persisted'")
        print(json.dumps({"image": image, "first": first, "restart": second,
                          "network": "none", "uid": 65532, "shellless": True,
                          "persistent_state": True,
                          "shutdown_exit": int(exit_code)}))
    except Exception:
        # Only an offline fixture with generated credentials ever runs here.
        try:
            print(docker("logs", "--tail", "40", name))
        except subprocess.CalledProcessError:
            pass
        raise
    finally:
        subprocess.run(["docker", "rm", "--force", name], check=False, stdout=subprocess.DEVNULL)
        if created:
            subprocess.run(["docker", "volume", "rm", volume], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("commit")
    parser.add_argument("build_id")
    args = parser.parse_args()
    smoke(args.image, args.commit, args.build_id)
