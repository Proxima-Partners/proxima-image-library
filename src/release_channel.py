"""SCM-only release RPC over the slot's private persistent filesystem.

No public HTTP endpoint, browser cookie, MCP secret or arbitrary command. Azure
SCM publishing permission is the authentication boundary. Only status, a bounded
one-record read probe and drain-on are accepted. Never undrain automatically.
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
        if not isinstance(request, dict) or set(request) != {"protocol", "nonce", "expires", "action"}:
            return False
        nonce = request["nonce"]
        now = self.clock()
        self.seen = {key: expiry for key, expiry in self.seen.items() if expiry > now}
        if (type(request["protocol"]) is not int or request["protocol"] != 1 or not isinstance(nonce, str)
                or not re.fullmatch(r"[a-f0-9]{32}", nonce) or nonce in self.seen
                or type(request["expires"]) is not int
                or not now < request["expires"] <= now + 60
                or not isinstance(request["action"], str)
                or request["action"] not in {"status", "probe", "drain"}):
            return False
        self.seen[nonce] = request["expires"]
        response = {"protocol": 1, "nonce": nonce, "action": request["action"],
                    "release_state": self.state, "release": self.release,
                    "slot": os.getenv("TELEMETRY_SLOT"), "workers": worker_count(), "ok": True}
        try:
            if request["action"] == "drain":
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
