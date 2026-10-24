import base64
import os

import pytest

from scripts import release_state_archive as archive


def test_capture_allowlist_only_preserves_bytes_and_metadata(tmp_path):
    allowed = tmp_path / "proxima_stock_keys.env"
    allowed.write_bytes(b"PRIVATE-fixture\n")
    allowed.chmod(0o600)
    (tmp_path / "unrelated.env").write_text("DO-NOT-COPY")
    directory = tmp_path / "proxima_maintenance_checkpoints"
    directory.mkdir()
    (directory / "checkpoint.json").write_text("{}")
    result = archive.capture(tmp_path)
    assert result["schema"] == 1
    assert len(result["entries"]) == 3
    entry = next(e for e in result["entries"] if e["path"] == allowed.name)
    assert base64.b64decode(entry["content"]) == allowed.read_bytes()
    assert entry["mode"] == 0o600 and entry["uid"] == os.getuid()
    assert all(e["path"] != "unrelated.env" for e in result["entries"])
    assert result == archive.capture(tmp_path)


def test_empty_root_is_explicit(tmp_path):
    assert archive.capture(tmp_path) == {"schema": 1, "entries": [], "bytes": 0, "missing": list(archive.ROOTS)}


@pytest.mark.parametrize("kind", ["file", "directory", "dangling", "fifo"])
def test_links_and_special_files_rejected(tmp_path, kind):
    path = tmp_path / "proxima_staged_uploads"
    if kind == "fifo":
        os.mkfifo(path)
    else:
        target = tmp_path / "target"
        if kind == "directory":
            target.mkdir()
        elif kind == "file":
            target.write_text("PRIVATE")
        path.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        archive.capture(tmp_path)


def test_nested_link_rejected(tmp_path):
    path = tmp_path / "proxima_staged_uploads"
    path.mkdir()
    (path / "link").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        archive.capture(tmp_path)


def test_byte_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MAX_BYTES", 3)
    (tmp_path / archive.ROOTS[0]).write_text("four")
    with pytest.raises(ValueError, match="byte limit"):
        archive.capture(tmp_path)


def test_entry_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MAX_ENTRIES", 1)
    (tmp_path / archive.ROOTS[0]).write_text("a")
    (tmp_path / archive.ROOTS[-1]).write_text("b")
    with pytest.raises(ValueError, match="entry limit"):
        archive.capture(tmp_path)


def test_replaced_file_detected(tmp_path, monkeypatch):
    path = tmp_path / archive.ROOTS[0]
    path.write_text("old")
    original = os.open
    def swapped(name, flags, *args, **kwargs):
        if name == path.name:
            path.unlink()
            path.write_text("new content")
        return original(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", swapped)
    with pytest.raises(ValueError, match="changed"):
        archive.capture(tmp_path)


def test_relative_or_symlink_root_rejected(tmp_path):
    with pytest.raises(ValueError):
        archive.capture("relative")
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    with pytest.raises(ValueError):
        archive.capture(link)
