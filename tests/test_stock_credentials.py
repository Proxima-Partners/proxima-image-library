import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.stock_credentials import KEYS, ManagedCredentialError, StockCredentials


def test_restart_loads_file_with_dotenv_disabled_without_interpolation(tmp_path):
    path = tmp_path / "proxima_stock_keys.env"
    store = StockCredentials(path, {})
    value = "literal-${SECRET}-\\-quote'\"-#-end"
    store.update("pexels", {"PEXELS_API_KEY": value})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    env = {k: v for k, v in os.environ.items() if k not in KEYS}
    env.update(PYTHON_DOTENV_DISABLED="1", SECRET="must-not-expand", APP_STATE_DIR=str(tmp_path))
    # A genuinely fresh Python process exercises the config import, not a reload
    # with credentials left in process memory. No values are printed.
    subprocess.run([sys.executable, "-c", "from src.config import stock_credentials; "
                    "import os,sys; assert os.environ['PEXELS_API_KEY'] == sys.argv[1]; "
                    "assert stock_credentials.editable('pexels')", value], env=env, check=True)


@pytest.mark.parametrize("external", ["azure-value", ""])
def test_environment_wins_and_provider_is_not_ui_editable(tmp_path, external):
    path = tmp_path / "keys.env"
    StockCredentials(path, {}).update("pexels", {"PEXELS_API_KEY": "file-value"})
    env = {"PEXELS_API_KEY": external}
    store = StockCredentials(path, env)
    before = path.read_bytes()
    assert env["PEXELS_API_KEY"] == external
    assert store.sources("pexels") == {"PEXELS_API_KEY": "environment"}
    with pytest.raises(ManagedCredentialError):
        store.update("pexels", {"PEXELS_API_KEY": "new"})
    assert path.read_bytes() == before
    assert env["PEXELS_API_KEY"] == external


@pytest.mark.parametrize("updates", [[], {}, {"OTHER": "no"},
    {"SHUTTERSTOCK_CLIENT_ID": "valid", "SHUTTERSTOCK_CLIENT_SECRET": ""},
    {"SHUTTERSTOCK_CLIENT_ID": "injection\nAPP_READ_ONLY=false"},
    {"SHUTTERSTOCK_CLIENT_ID": None}, {"SHUTTERSTOCK_CLIENT_ID": "nul\x00value"},
    {"SHUTTERSTOCK_CLIENT_ID": "a" * 4097}])
def test_invalid_request_has_no_partial_changes(tmp_path, updates):
    env = {}
    store = StockCredentials(tmp_path / "keys.env", env)
    with pytest.raises(ValueError):
        store.update("shutterstock", updates)
    assert env == {}
    assert not store.path.exists()


def test_replace_failure_keeps_disk_and_environment_unchanged(tmp_path, monkeypatch):
    env = {}
    store = StockCredentials(tmp_path / "keys.env", env)
    store.update("pexels", {"PEXELS_API_KEY": "before"})
    before = store.path.read_bytes()
    def fail(*_):
        raise OSError("fixture disk failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.update("pexels", {"PEXELS_API_KEY": "after"})
    assert store.path.read_bytes() == before
    assert env == {"PEXELS_API_KEY": "before"}
    assert list(tmp_path.iterdir()) == [store.path]


def test_post_replace_sync_failure_requires_reconciliation_not_blind_retry(tmp_path, monkeypatch):
    env = {}
    store = StockCredentials(tmp_path / "keys.env", env)
    real_sync = os.fsync
    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory sync failed after replacement")
        return real_sync(fd)
    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(OSError):
        store.update("pexels", {"PEXELS_API_KEY": "possibly-saved"})
    assert env == {}
    with pytest.raises(RuntimeError, match="externally"):
        store.update("pexels", {"PEXELS_API_KEY": "do-not-retry"})
    # A new process/store reconciles the file; the failed request never claims
    # the old file was restored after an acknowledged replace.
    assert StockCredentials(store.path, {}).environ["PEXELS_API_KEY"] == "possibly-saved"


@pytest.mark.parametrize("content", ["APP_READ_ONLY=false\n", "PEXELS_API_KEY='unterminated\n",
    "PEXELS_API_KEY=a\nPEXELS_API_KEY=b\n", "PEXELS_API_KEY\n", "x" * 33000])
def test_invalid_file_fails_closed_without_loading_settings(tmp_path, content):
    path = tmp_path / "keys.env"
    path.write_text(content)
    env = {}
    with pytest.raises(ValueError):
        StockCredentials(path, env)
    assert env == {}
    assert path.read_text() == content


def test_symlink_and_external_edit_are_not_overwritten(tmp_path):
    target = tmp_path / "target"
    target.write_text("PEXELS_API_KEY=original\n")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        StockCredentials(link, {})
    store = StockCredentials(target, {})
    target.write_text("PEXELS_API_KEY=external\n")
    with pytest.raises(RuntimeError, match="externally"):
        store.update("pexels", {"PEXELS_API_KEY": "no-overwrite"})
    assert target.read_text() == "PEXELS_API_KEY=external\n"


def test_serialized_updates_preserve_other_provider_and_reload(tmp_path):
    path = tmp_path / "keys.env"
    store = StockCredentials(path, {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(store.update, "pexels", {"PEXELS_API_KEY": "pexels"})
        b = pool.submit(store.update, "pixabay", {"PIXABAY_API_KEY": "pixabay"})
        a.result()
        b.result()
    env = {}
    reloaded = StockCredentials(path, env)
    assert env == {"PEXELS_API_KEY": "pexels", "PIXABAY_API_KEY": "pixabay"}
    assert reloaded.sources("pexels")["PEXELS_API_KEY"] == "persistent"
    assert reloaded.editable("pexels")
