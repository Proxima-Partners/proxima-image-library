"""Bounded, read-only state capture. The returned bundle contains PRIVATE data.

Never print a bundle or put it in GitHub artifacts. Store only in the approved
private backup container or owner-only local recovery storage. No restore CLI.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat

ROOTS = (
    "proxima_maintenance_state.json", "proxima_maintenance_checkpoints",
    "proxima_staged_uploads", "proxima_ss_counter.json", "proxima_stock_keys.env",
    "tag_library.json",
)
MAX_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 1000


def capture(root):
    root = Path(root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid state root")
    entries, missing, total = [], [], 0

    def signature(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def visit(parent, name, relative):
        nonlocal total
        if len(entries) >= MAX_ENTRIES:
            raise ValueError("State entry limit exceeded")
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        entry = {"path": relative, "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid}
        if stat.S_ISDIR(info.st_mode):
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                if signature(os.fstat(fd)) != signature(info):
                    raise ValueError("State changed while capturing")
                entries.append(dict(entry, kind="directory"))
                children = sorted(os.listdir(fd))
                if len(children) + len(entries) > MAX_ENTRIES:
                    raise ValueError("State entry limit exceeded")
                for child in children:
                    visit(fd, child, relative + "/" + child)
                if children != sorted(os.listdir(fd)) or signature(os.fstat(fd)) != signature(info):
                    raise ValueError("State changed while capturing")
            finally:
                os.close(fd)
        elif stat.S_ISREG(info.st_mode):
            if total + info.st_size > MAX_BYTES:
                raise ValueError("State byte limit exceeded")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or signature(opened) != signature(info):
                    raise ValueError("State changed while capturing")
                value = stream.read(MAX_BYTES - total + 1)
                after = os.fstat(stream.fileno())
            if (len(value) != info.st_size or signature(opened) != signature(after)
                    or len(value) + total > MAX_BYTES):
                raise ValueError("State changed or exceeded byte limit")
            total += len(value)
            entries.append(dict(entry, kind="file", size=len(value), sha256=hashlib.sha256(value).hexdigest(),
                                content=base64.b64encode(value).decode()))
        else:
            raise ValueError("State contains link or special file")
        if signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != signature(info):
            raise ValueError("State changed while capturing")

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in ROOTS:
            try:
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                missing.append(name)
            else:
                visit(descriptor, name, name)
        for name in missing:
            try:
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ValueError("State changed while capturing")
    finally:
        os.close(descriptor)
    return {"schema": 1, "entries": entries, "missing": missing, "bytes": total}


if __name__ == "__main__":
    # Called only through authenticated SCM; the caller captures this PRIVATE
    # output in memory, never a terminal, deployment log or public artifact.
    print(json.dumps(capture("/home"), separators=(",", ":")))
