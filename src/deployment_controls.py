"""Single-process release containment. No network calls or import-time writers.

Read-only is fail-closed and drain survives restarts. Work already admitted may
finish during drain. This is NOT a distributed lease or permission to scale out.
"""

import functools
import hashlib
import os
import re
import stat
import tempfile
import threading
import uuid
from pathlib import Path

_lock = threading.RLock()
_active = set()


def state_path(name, local_fallback):
    root = os.getenv("APP_STATE_DIR", "").strip()
    if root:
        return Path(root) / name
    if os.getenv("WEBSITE_INSTANCE_ID") and Path("/home").exists():
        return Path("/home") / name
    return Path(local_fallback)


def read_only():
    # A misspelling must never accidentally enable writes.
    return os.getenv("APP_READ_ONLY", "false").strip().lower() not in {"0", "false", "no"}


def drain_path():
    return state_path("proxima_deployment_drain", Path(tempfile.gettempdir()) / "proxima_deployment_drain")


def draining():
    try:
        return drain_path().exists()
    except OSError:
        return True


def snapshot():
    with _lock:
        return {"read_only": read_only(), "draining": draining(), "active_work": len(_active)}


def set_drain(enabled):
    with _lock:
        path = drain_path()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(mode=0o600, exist_ok=True)
        else:
            path.unlink(missing_ok=True)
        return snapshot()


class WritesDisabled(RuntimeError):
    pass


def writable(func):
    """Defense in depth on Graph writes, without aborting admitted drain work."""
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        if read_only():
            raise WritesDisabled("Application is read-only")
        return func(*args, **kwargs)
    return wrapped


class Work:
    def __init__(self, *, admitted=False):
        with _lock:
            if read_only() or (draining() and not admitted):
                raise WritesDisabled("Application is read-only or draining")
            self.token = object()
            _active.add(self.token)

    def close(self):
        with _lock:
            _active.discard(self.token)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class WorkThread(threading.Thread):
    """Count before start and until the worker really exits, even if SSE closes."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._work = None

    def start(self):
        if self._work is not None:
            raise RuntimeError("threads can only be started once")
        self._work = Work(admitted=True)
        try:
            super().start()
        except BaseException:
            self._work.close()
            raise

    def run(self):
        try:
            super().run()
        finally:
            self._work.close()


def poller_enabled():
    return (
        os.getenv("INGEST_POLLER_ENABLED", "false").lower() == "true"
        and not read_only()
        and bool(os.getenv("INGEST_OWNER_HOSTNAME"))
        and os.getenv("INGEST_OWNER_HOSTNAME") == os.getenv("WEBSITE_HOSTNAME")
    )


def verify_state_directory():
    """Check an explicitly configured mount without touching application data."""
    root = os.getenv("APP_STATE_DIR", "").strip()
    if not root:
        return
    path = Path(root)
    if not path.is_absolute() or not path.is_dir():
        raise RuntimeError("APP_STATE_DIR must be an existing absolute directory")
    with tempfile.TemporaryDirectory(prefix=".readiness-", dir=path) as temporary:
        source = Path(temporary) / "probe"
        source.write_bytes(b"ready")
        source.rename(Path(temporary) / "renamed")
    if os.getenv("PILOT_STATE_PROBE_ENABLED", "false").lower() != "true":
        return None
    if not read_only() or os.getenv("INGEST_POLLER_ENABLED", "false").lower() != "false":
        raise RuntimeError("Persistent pilot probe requires read-only mode and ingestion disabled")
    # A non-secret, pilot-only sentinel lets the operator prove the actual
    # mounted state survives new image deployments, restarts and slot swaps.
    # Never overwrite an existing file or follow a link into application data.
    marker = path / ".image-library-pilot-state"
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(uuid.uuid4().hex.encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
    fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RuntimeError("Invalid pilot state sentinel")
        data = stream.read(33)
    if not re.fullmatch(rb"[a-f0-9]{32}", data):
        raise RuntimeError("Invalid pilot state sentinel")
    return {"state_id": hashlib.sha256(data).hexdigest(), "boot_id": uuid.uuid4().hex,
            "uid": os.getuid(), "gid": os.getgid()}
