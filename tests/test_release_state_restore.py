import copy
import os
import sys

import pytest

from scripts.release_state_archive import capture
from scripts.release_state_restore import restore_isolated, install_isolated, validate


@pytest.fixture
def bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "proxima_maintenance_state.json").write_bytes(b'{"history":[]}')
    nested = source / "proxima_staged_uploads" / "nested"
    nested.mkdir(parents=True)
    (nested / "fixture.bin").write_bytes(bytes(range(256)))
    return capture(source)


def test_private_restore_roundtrip_and_normalization(tmp_path, bundle):
    destination = tmp_path.resolve() / "restore"
    result = restore_isolated(bundle, destination, uid=os.getuid(), gid=os.getgid())
    assert result["verified"] and not result["published_to_live_roots"]
    assert result["files"] == 2
    observed = capture(destination)
    assert validate(observed) == validate(bundle)
    assert all(e["mode"] == (0o600 if e["kind"] == "file" else 0o700) for e in observed["entries"])


@pytest.mark.parametrize("kind", ["empty", "occupied", "symlink"])
def test_never_overwrite_destination(tmp_path, bundle, kind):
    destination = tmp_path.resolve() / "restore"
    if kind == "symlink":
        destination.symlink_to(tmp_path / "source", target_is_directory=True)
    else:
        destination.mkdir()
        if kind == "occupied":
            (destination / "precious").write_text("keep")
    with pytest.raises(FileExistsError):
        restore_isolated(bundle, destination, uid=os.getuid(), gid=os.getgid())
    if kind == "occupied":
        assert (destination / "precious").read_text() == "keep"


@pytest.mark.parametrize("change", [
    lambda b: b.update(schema=True),
    lambda b: b.update(bytes=-1),
    lambda b: b.update(bytes=1),
    lambda b: b.update(extra="no"),
    lambda b: b["missing"].append(b["missing"][0]),
    lambda b: b["missing"].append("proxima_maintenance_state.json"),
    lambda b: b["missing"].pop(),
    lambda b: b["entries"].append(copy.deepcopy(b["entries"][0])),
    lambda b: b["entries"][0].update(path="/etc/passwd"),
    lambda b: b["entries"][0].update(path="proxima_staged_uploads/../escape"),
    lambda b: b["entries"][0].update(path="proxima_staged_uploads//escape"),
    lambda b: b["entries"][0].update(path="proxima_staged_uploads/./escape"),
    lambda b: b["entries"][0].update(path="proxima_staged_uploads\\escape"),
    lambda b: b["entries"][0].update(path="proxima_staged_uploads/missing/child"),
    lambda b: b["entries"][0].update(kind="symlink"),
    lambda b: b["entries"][0].update(mode=0o4755),
    lambda b: b["entries"][0].update(uid=True),
    lambda b: b["entries"][0].update(content="*"),
    lambda b: b["entries"][0].update(sha256="wrong"),
    lambda b: b["entries"][0].update(size=True),
    lambda b: b["entries"][0].update(size=0),
])
def test_invalid_bundle_rejected_before_any_creation(tmp_path, bundle, change):
    change(bundle)
    destination = tmp_path.resolve() / "restore"
    with pytest.raises(ValueError):
        restore_isolated(bundle, destination, uid=os.getuid(), gid=os.getgid())
    assert not destination.exists()


def test_parent_symlink_rejected(tmp_path, bundle):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        restore_isolated(bundle, link / "restore", uid=os.getuid(), gid=os.getgid())


def test_interrupted_restore_preserves_isolated_evidence(tmp_path, bundle, monkeypatch):
    def failed(*args):
        raise OSError("simulated fsync failure")
    monkeypatch.setattr(os, "fsync", failed)
    destination = tmp_path.resolve() / "restore"
    with pytest.raises(OSError):
        restore_isolated(bundle, destination, uid=os.getuid(), gid=os.getgid())
    assert destination.is_dir()
    with pytest.raises(FileExistsError):
        restore_isolated(bundle, destination, uid=os.getuid(), gid=os.getgid())


@pytest.mark.skipif(sys.platform != "linux", reason="Linux atomic rename contract")
def test_empty_target_install_preserves_other_files(tmp_path, bundle):
    source, target = tmp_path.resolve()/"restore", tmp_path.resolve()/"target"
    restore_isolated(bundle, source, uid=os.getuid(), gid=os.getgid())
    original = capture(source)
    target.mkdir()
    (target/".mount-sentinel").write_text("unchanged")
    result = install_isolated(bundle, source, target)
    assert result["verified"] and result["existing_state_overwritten"] is False
    assert capture(target) == original
    assert (target/".mount-sentinel").read_text() == "unchanged"
    assert "installed_and_verified" in (source/".install-journal.jsonl").read_text()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux atomic rename contract")
@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_install_refuses_any_existing_root_before_journal(tmp_path, bundle, kind):
    source, target = tmp_path.resolve()/"restore", tmp_path.resolve()/"target"
    restore_isolated(bundle, source, uid=os.getuid(), gid=os.getgid())
    target.mkdir()
    occupied = target/"proxima_staged_uploads"
    if kind == "file":
        occupied.write_text("precious")
    elif kind == "directory":
        occupied.mkdir()
    else:
        occupied.symlink_to(source)
    with pytest.raises(FileExistsError):
        install_isolated(bundle, source, target)
    assert not (source/".install-journal.jsonl").exists()
    assert not (target/"proxima_maintenance_state.json").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux atomic rename contract")
def test_ambiguous_install_keeps_journal_and_prevents_replay(tmp_path, bundle, monkeypatch):
    source, target = tmp_path.resolve()/"restore", tmp_path.resolve()/"target"
    restore_isolated(bundle, source, uid=os.getuid(), gid=os.getgid())
    target.mkdir()
    original_fsync = os.fsync
    def fail_target(fd):
        if os.fstat(fd).st_ino == target.stat().st_ino:
            raise OSError("simulated interrupted acknowledgement")
        original_fsync(fd)
    monkeypatch.setattr(os,"fsync",fail_target)
    with pytest.raises(OSError):
        install_isolated(bundle, source, target)
    assert (target/"proxima_maintenance_state.json").exists()
    assert (source/".install-journal.jsonl").exists()
    with pytest.raises(ValueError):
        install_isolated(bundle, source, target)
