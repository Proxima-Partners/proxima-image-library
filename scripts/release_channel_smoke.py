"""Offline release-channel fixture; no Azure, Graph, real credentials or app data.

Exercise the actual single Gunicorn worker, persistent drain and fresh boot on
the exact runtime image. This does not validate SCM ownership or Azure mounts.
"""
import argparse
import json
import os
import secrets
import subprocess
import time
import uuid

from scripts.container_smoke import docker, PROBE


def smoke(image, commit, build_id):
    name = "image-library-release-smoke-" + uuid.uuid4().hex[:12]
    volume = name + "-state"
    created = False
    environment = dict(os.environ, FLASK_SECRET_KEY=secrets.token_hex(32))
    try:
        docker("volume", "create", volume)
        created = True
        docker("run", "--detach", "--platform", "linux/amd64", "--name", name,
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=64m",
               "--mount", f"type=volume,source={volume},target=/home",
               "--env", "FLASK_SECRET_KEY", "--env", "TELEMETRY_ENABLED=false",
               "--env", "APP_READ_ONLY=false", "--env", "PILOT_STATE_PROBE_ENABLED=false",
               "--env", "PRODUCTION_RELEASE_CONTROL_ENABLED=true", "--env", "TELEMETRY_SLOT=production",
               "--env", f"EXPECTED_COMMIT={commit}", "--env", f"EXPECTED_BUILD_ID={build_id}",
               image, env=environment)

        def ready():
            for _ in range(45):
                try:
                    json.loads(docker("exec", name, "python", "-c", PROBE, stderr=subprocess.DEVNULL))
                    return
                except (subprocess.CalledProcessError, json.JSONDecodeError):
                    time.sleep(1)
            raise RuntimeError("Offline release runtime readiness failed")

        def control(action):
            nonce = uuid.uuid4().hex
            code = (
                "import json,os,time; from pathlib import Path; "
                "p=Path('/home/.image-library-release-control/request.json'); "
                "fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600); "
                f"os.write(fd,json.dumps(dict(protocol=1,nonce='{nonce}',expires=int(time.time())+60,action='{action}')).encode()); "
                "os.fsync(fd); os.close(fd)"
            )
            docker("exec", name, "python", "-c", code)
            for _ in range(15):
                try:
                    result = json.loads(docker("exec", name, "python", "-c",
                        "from pathlib import Path; print(Path('/home/.image-library-release-control/response.json').read_text())",
                        stderr=subprocess.DEVNULL))
                    if result["nonce"] == nonce:
                        assert result["ok"] is True and result["workers"] == 1
                        assert result["active_work"] == 0 and result["read_only"] is False
                        assert result["release"]["commit"] == commit and result["release"]["build_id"] == build_id
                        return result
                except (subprocess.CalledProcessError, json.JSONDecodeError):
                    pass
                time.sleep(1)
            raise RuntimeError("Offline release-channel response timed out")

        ready()
        first = control("status")
        assert first["draining"] is False
        assert control("drain")["draining"] is True
        docker("stop", "--time", "15", name)
        assert docker("inspect", "--format", "{{.State.ExitCode}}", name) == "0"
        docker("start", name)
        ready()
        second = control("status")
        assert second["draining"] is True
        assert first["release_state"]["state_id"] == second["release_state"]["state_id"]
        assert first["release_state"]["boot_id"] != second["release_state"]["boot_id"]
        assert second["release_state"]["uid"] == second["release_state"]["gid"] == 65532
        print(json.dumps({"status": "passed", "image": image, "build_id": build_id,
            "network": "none", "workers": 1, "drain_survived_restart": True,
            "mount_preserved": True, "fresh_boot": True, "shutdown_exit": 0,
            "azure_scm_or_graph_verified": False}))
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
