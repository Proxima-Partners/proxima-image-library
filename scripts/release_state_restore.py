"""Strict private-state recovery staging and supervised empty-target install.

restore_isolated never publishes live roots. install_isolated is a separate
explicit primitive for a stopped, leased target; neither is an automatic restore.
Failure leaves the isolated directory for reconciliation; it never deletes data.
Bytes are preserved. Strict POSIX mode normalizes permissions; the explicitly
approved azure_shared policy verifies Azure's fixed metadata without claiming
owner-only protection. Azure shared state must contain no credential file.
"""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time

from scripts.release_state_archive import MAX_BYTES, MAX_ENTRIES, ROOTS, StateChangedError, capture

DIRECTORIES = {"proxima_maintenance_checkpoints", "proxima_staged_uploads"}
AZURE_METADATA = (65534, 65534, 0o777)


def _metadata(info):
    return info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)


def _shared_mount_check(info):
    if _metadata(info) != AZURE_METADATA:
        raise ValueError("Azure shared mount metadata differs; no permission fallback")


def _policy_entries(bundle, policy):
    entries = validate(bundle)
    if policy not in {"strict_posix", "azure_shared"}:
        raise ValueError("Unknown state restore policy")
    if policy == "azure_shared":
        if "proxima_stock_keys.env" in entries:
            raise ValueError("Credential files cannot be installed on Azure shared state")
        if any(p.startswith("proxima_staged_uploads/") for p in entries):
            raise ValueError("Staged uploads require separate reconciliation; no replay")
    return entries


def capture_settled(root, *, pause=time.sleep):
    """Bounded READ-ONLY reconciliation of Azure's post-write metadata cache.

    Requires two consecutive identical, internally stable captures. No writes
    are retried and no invariant is relaxed. This is not writer containment.
    All other errors fail immediately; prolonged instability fails closed.
    """
    prior = None
    for attempt in range(12):
        try:
            observed = capture(root)
        except StateChangedError:
            prior = None
        else:
            if observed == prior:
                return observed
            prior = observed
        if attempt < 11:
            pause(0.5)
    raise StateChangedError("State did not settle; preserve for reconciliation")


def validate(bundle):
    """Validate everything before creating a destination. Returns private bytes."""
    def fail():
        raise ValueError("Invalid private state archive")

    if not isinstance(bundle, dict) or set(bundle) != {"schema", "entries", "missing", "bytes"}:
        fail()
    if type(bundle["schema"]) is not int or bundle["schema"] != 1:
        fail()
    entries, missing = bundle["entries"], bundle["missing"]
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES or not isinstance(missing, list):
        fail()
    if any(not isinstance(p, str) or p not in ROOTS for p in missing) or len(set(missing)) != len(missing):
        fail()
    if type(bundle["bytes"]) is not int or not 0 <= bundle["bytes"] <= MAX_BYTES:
        fail()
    result, total = {}, 0
    for entry in entries:
        if not isinstance(entry, dict):
            fail()
        path = entry.get("path")
        if (not isinstance(path, str) or not path or len(path.encode()) > 4096
                or any(ord(c) < 32 for c in path) or "\\" in path
                or any(p in ("", ".", "..") for p in path.split("/"))):
            fail()
        parts = PurePosixPath(path).parts
        if parts[0] not in ROOTS or path in result:
            fail()
        kind = entry.get("kind")
        expected = {"path", "mode", "uid", "gid", "kind"}
        if kind == "file":
            expected |= {"size", "sha256", "content"}
        elif kind != "directory":
            fail()
        if set(entry) != expected:
            fail()
        if any(type(entry[k]) is not int or not 0 <= entry[k] <= 2**32-2 for k in ("uid", "gid")):
            fail()
        if type(entry["mode"]) is not int or not 0 <= entry["mode"] <= 0o777:
            fail()
        if len(parts) == 1 and (kind == "directory") != (path in DIRECTORIES):
            fail()
        content = None
        if kind == "file":
            size, encoded = entry["size"], entry["content"]
            if (type(size) is not int or not 0 <= size <= MAX_BYTES-total
                    or not isinstance(encoded, str) or len(encoded) != 4*((size+2)//3)):
                fail()
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                fail()
            if (len(content) != size or base64.b64encode(content).decode() != encoded
                    or hashlib.sha256(content).hexdigest() != entry["sha256"]):
                fail()
            total += size
        result[path] = (kind, content)
    for path in result:
        parent = str(PurePosixPath(path).parent)
        if parent != "." and (parent not in result or result[parent][0] != "directory"):
            fail()
    present = {p for p in result if "/" not in p}
    if present & set(missing) or present | set(missing) != set(ROOTS) or total != bundle["bytes"]:
        fail()
    return result


def restore_isolated(bundle, destination, *, uid=None, gid=None, policy="strict_posix"):
    """Exclusive new directory; normalized 0600 files / 0700 directories.

    Use only a protected canonical parent, with all application writers stopped.
    This function does NOT publish files into /home or overwrite an existing root.
    """
    entries = _policy_entries(bundle, policy)
    shared = policy == "azure_shared"
    destination = Path(destination)
    if (not destination.is_absolute() or destination.name in ("", ".", "..")
            or destination.parent.resolve(strict=True) != destination.parent
            or (not shared and any(type(n) is not int or not 0 <= n <= 2**32-2 for n in (uid, gid)))
            or (shared and (uid is not None or gid is not None))):
        raise ValueError("Invalid isolated restore destination or owner")
    parent = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened = {}
    try:
        if shared:
            _shared_mount_check(os.fstat(parent))
        os.mkdir(destination.name, 0o700, dir_fd=parent)  # EXCLUSIVE, even for empty existing directories.
        root = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        opened["."] = root
        if shared:
            _shared_mount_check(os.fstat(root))
        else:
            os.fchmod(root, 0o700)
        for path, (kind, content) in sorted(entries.items(), key=lambda pair: (pair[0].count("/"), pair[0])):
            relative = PurePosixPath(path)
            directory = opened[str(relative.parent)]
            if kind == "directory":
                os.mkdir(relative.name, 0o700, dir_fd=directory)
                descriptor = os.open(relative.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                opened[path] = descriptor
                if shared:
                    _shared_mount_check(os.fstat(descriptor))
                else:
                    os.fchmod(descriptor, 0o700)
            else:
                descriptor = os.open(relative.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=directory)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    if shared:
                        _shared_mount_check(os.fstat(stream.fileno()))
                    else:
                        os.fchmod(stream.fileno(), 0o600)
                        if (os.fstat(stream.fileno()).st_uid, os.fstat(stream.fileno()).st_gid) != (uid, gid):
                            os.fchown(stream.fileno(), uid, gid)
                    os.fsync(stream.fileno())
        # Chown directories only AFTER all private children have been written.
        for descriptor in reversed(list(opened.values())):
            if shared:
                _shared_mount_check(os.fstat(descriptor))
            elif (os.fstat(descriptor).st_uid, os.fstat(descriptor).st_gid) != (uid, gid):
                os.fchown(descriptor, uid, gid)
            os.fsync(descriptor)
        info = os.fstat(root)
        if _metadata(info) != (AZURE_METADATA if shared else (uid, gid, 0o700)):
            raise RuntimeError("Isolated restore root ownership or mode differs")
        os.fsync(parent)
    finally:
        for descriptor in opened.values():
            os.close(descriptor)
        os.close(parent)
    observed = capture_settled(destination) if shared else capture(destination)
    if validate(observed) != entries:
        raise RuntimeError("Restored private state differs; preserve for reconciliation")
    if any((e["uid"], e["gid"], e["mode"]) != (AZURE_METADATA if shared else
           (uid, gid, 0o700 if e["kind"] == "directory" else 0o600)) for e in observed["entries"]):
        raise RuntimeError("Restore ownership or mode differs; preserve for reconciliation")
    return {"verified": True, "files": sum(k == "file" for k, _ in entries.values()),
            "entries": len(entries), "bytes": bundle["bytes"], "policy": policy,
            "uid": AZURE_METADATA[0] if shared else uid, "gid": AZURE_METADATA[1] if shared else gid,
            "owner_only_permissions": not shared,
            "published_to_live_roots": False}


def install_isolated(bundle, source, destination, *, policy="strict_posix"):
    """Publish into an EMPTY set of allowlisted roots; Linux only, no overwrite.

    CALLER MUST hold the release lease and prove source/target apps stopped.
    Each root rename is atomic, but the whole group is NOT a transaction. An
    error leaves partial state and an fsynced journal; never retry automatically.
    Other files (including mount sentinels) in destination are not touched.
    """
    expected = _policy_entries(bundle, policy)
    source, destination = Path(source), Path(destination)
    for path in (source, destination):
        if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_dir():
            raise ValueError("Noncanonical install directory")
    if source == destination or destination.is_relative_to(source):
        raise ValueError("Unsafe install directory relationship")
    original = capture_settled(source) if policy == "azure_shared" else capture(source)
    if validate(original) != expected:
        raise ValueError("Isolated source differs from approved private bundle")
    # Linux renameat2(RENAME_NOREPLACE) is deliberately required. os.rename can
    # silently overwrite an existing empty directory on Unix, which is unsafe.
    rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if rename is None:
        raise RuntimeError("Atomic no-overwrite install requires Linux renameat2")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    target_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if policy == "azure_shared":
            _shared_mount_check(os.fstat(source_fd))
            _shared_mount_check(os.fstat(target_fd))
            if any((e["uid"], e["gid"], e["mode"]) != AZURE_METADATA for e in original["entries"]):
                raise ValueError("Isolated Azure source metadata differs")
        if os.fstat(source_fd).st_dev != os.fstat(target_fd).st_dev:
            raise ValueError("Install requires the same filesystem")
        for name in ROOTS:
            try:
                os.stat(name, dir_fd=target_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise FileExistsError("Target state is not empty; never overwrite or merge")
        fd = os.open(".install-journal.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=source_fd)
        with os.fdopen(fd, "w") as journal:
            def record(phase, name=None):
                journal.write(json.dumps({"phase": phase, "root": name}) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
                os.fsync(source_fd)

            record("begin_empty_target_install")
            for name in ROOTS:
                if name not in expected:
                    continue
                record("rename_intent", name)
                if rename(source_fd, os.fsencode(name), target_fd, os.fsencode(name), 1) != 0:
                    raise OSError(ctypes.get_errno(), "No-overwrite install failed; reconcile journal")
                os.fsync(target_fd)
                os.fsync(source_fd)
                record("rename_acknowledged", name)
            observed = capture_settled(destination) if policy == "azure_shared" else capture(destination)
            if observed != original:
                raise RuntimeError("Installed bytes or metadata differ; keep target stopped")
            record("installed_and_verified")
    finally:
        os.close(source_fd)
        os.close(target_fd)
    return {"verified": True, "policy": policy, "published_roots": [name for name in ROOTS if name in expected],
            "existing_state_overwritten": False, "automatic_rollback": False}
