"""SCM-only release RPC over the slot's app-isolated persistent filesystem.

No public HTTP endpoint, browser cookie, MCP secret or arbitrary command. Azure
SCM publishing permission is the authentication boundary, NOT /home file modes.
Status, bounded catalog/filesystem probes and drain-on are accepted by default.
Resume needs a separately enabled runtime flag and exact build/boot/mount binding.
No secrets or record contents are exchanged. Resume is disabled by default.
"""
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time

from src import deployment_controls as controls

DIRECTORY = ".image-library-release-control"
MAX_BYTES = 4096


def state_probe(root, nonce):
    """Prove actual worker access using only one exclusive non-secret fixture.

    No caller-selected paths, recursive cleanup, existing-state writes or retry.
    A failed probe preserves its fixture for explicit reconciliation.
    """
    if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise ValueError("Invalid probe nonce")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    name = ".image-library-state-probe-" + nonce
    directory = None
    try:
        os.mkdir(name, 0o700, dir_fd=root_fd)  # Never adopt or remove an existing directory.
        directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        fd = os.open("original", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        data = b"image-library-nonsecret-state-probe-v1\n"
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            info = os.fstat(stream.fileno())
        os.rename("original", "renamed", src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
        fd = os.open("renamed", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read(len(data)+1) != data:
                raise RuntimeError("State probe bytes differ")
        os.unlink("renamed", dir_fd=directory)
        os.fsync(directory)
        os.rmdir(name, dir_fd=root_fd)
        os.fsync(root_fd)
        try:
            os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return {"uid": os.getuid(), "gid": os.getgid(),
                    "file_uid": info.st_uid, "file_gid": info.st_gid,
                    "file_mode": stat.S_IMODE(info.st_mode),
                    "read_write_rename": True, "cleanup_verified": True}
        raise RuntimeError("State probe cleanup differs")
    finally:
        if directory is not None:
            os.close(directory)
        os.close(root_fd)


def worker_count():
    """Actual Linux process evidence; never confuse App Service instances with workers."""
    try:
        if os.getppid() != 1 or b"gunicorn" not in Path("/proc/1/cmdline").read_bytes():
            return None
        children = Path("/proc/1/task/1/children").read_text().split()
        if children != [str(os.getpid())]:
            return None
        return 1
    except (OSError, ValueError):
        return None


class ReleaseChannel:
    def __init__(self, root, state, release, read_probe, *, clock=time.time):
        self.directory = Path(root) / DIRECTORY
        self.directory.mkdir(mode=0o700, exist_ok=True)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise RuntimeError("Invalid release control directory")
        self.state, self.release, self.read_probe = state, release, read_probe
        self.clock = clock
        self.seen = {}
        self.stop = threading.Event()

    def process_once(self):
        try:
            fd = os.open(self.directory / "request.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return False
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return False
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return False
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeError):
            return False
        fields = {"protocol", "nonce", "expires", "action"}
        if isinstance(request, dict) and request.get("action") == "resume":
            fields.add("expected")
        if not isinstance(request, dict) or set(request) != fields:
            return False
        nonce = request["nonce"]
        now = self.clock()
        self.seen = {key: expiry for key, expiry in self.seen.items() if expiry > now}
        if (type(request["protocol"]) is not int or request["protocol"] not in {1, 2} or not isinstance(nonce, str)
                or not re.fullmatch(r"[a-f0-9]{32}", nonce) or nonce in self.seen
                or type(request["expires"]) is not int
                or not now < request["expires"] <= now + 60
                or not isinstance(request["action"], str)
                or request["action"] not in {"status", "probe", "state_probe", "drain", "resume"}):
            return False
        self.seen[nonce] = request["expires"]
        response = {"protocol": request["protocol"], "nonce": nonce, "action": request["action"],
                    "release_state": self.state, "release": self.release,
                    "slot": os.getenv("TELEMETRY_SLOT"), "workers": worker_count(), "ok": True}
        try:
            if request["protocol"] == 2:
                # One-shot protocol: retire the exact request durably BEFORE
                # acting. A crash cannot replay a resume against a later boot.
                path = self.directory / "request.json"
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    info = os.fstat(descriptor)
                    if not stat.S_ISREG(info.st_mode) or os.read(descriptor, MAX_BYTES + 1) != raw:
                        raise RuntimeError("One-shot request changed")
                    current = os.stat(path, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                        raise RuntimeError("One-shot request replaced")
                    os.unlink(path)
                    directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    os.close(descriptor)
                response["request_retired"] = True
            if request["action"] == "resume":
                expected = {"commit": self.release.get("commit"), "build_id": self.release.get("build_id"),
                            "state_id": self.state.get("state_id"), "boot_id": self.state.get("boot_id")}
                if (os.getenv("PRODUCTION_RELEASE_RESUME_ENABLED") != "true"
                        or os.getenv("TELEMETRY_SLOT") != "production"
                        or os.getenv("INGEST_POLLER_ENABLED") != "false"
                        or worker_count() != 1 or not all(expected.values())
                        or request["expected"] != expected):
                    raise RuntimeError("Resume policy or exact runtime binding differs")
                controls.resume_if_idle()
            elif request["action"] == "drain":
                controls.set_drain(True)
                marker = controls.drain_path()
                descriptor = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise RuntimeError("Invalid drain marker")
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                descriptor = os.open(marker.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            elif request["action"] == "state_probe":
                response["state_probe"] = state_probe(self.directory.parent, nonce)
            elif request["action"] == "probe":
                # Callback must read at most one record, not enumerate/download
                # the catalog. No record contents leave this channel.
                count = self.read_probe()
                if type(count) is not int or not 0 <= count <= 1:
                    raise RuntimeError("Invalid bounded read result")
                response["sample_records"] = count
        except Exception:
            response["ok"] = False  # Never serialize SDK/credential exceptions.
        response.update(controls.snapshot())
        response["at"] = int(self.clock())
        fd, name = tempfile.mkstemp(prefix=".response-", dir=self.directory)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(response, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.directory / "response.json")
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)
        return True

    def run(self):
        while not self.stop.is_set():
            try:
                self.process_once()
            except Exception:
                # Transport/file failures mean no fresh acknowledgement. The
                # controller times out and stays locked/drained; app stays up.
                pass
            self.stop.wait(1)

    def start(self):
        thread = threading.Thread(target=self.run, name="release-control", daemon=True)
        thread.start()
        return thread
