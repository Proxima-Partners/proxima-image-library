import pytest

from scripts.cutover_checkpoint import upload_verified
from scripts.release_azure_io import AzureIOError, STORAGE
from scripts import cutover_checkpoint as checkpoint_module


class Lease:
    run_id = "test-run"
    def assert_held(self):
        self.checked = True


class Transport:
    def __init__(self, changed=False):
        self.calls, self.changed = [], changed
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "PUT":
            self.value = kwargs["data"]
            return 201, {}, b""
        return 200, {}, self.value + (b"changed" if self.changed else b"")


def test_private_backup_exclusive_and_exact_readback():
    lease, transport = Lease(), Transport()
    private = b"private-fixture"
    assert upload_verified(transport, lease, "legacy-production.json.gz", private) == private
    assert lease.checked
    method, url, args = transport.calls[0]
    assert method == "PUT" and url.startswith(STORAGE + "/rollback-backups/test-run/")
    assert args["headers"]["If-None-Match"] == "*"


def test_changed_readback_fails_without_retry():
    transport = Transport(changed=True)
    with pytest.raises(AzureIOError):
        upload_verified(transport, Lease(), "legacy-staging.source.tar", b"private-fixture")
    assert len(transport.calls) == 2


@pytest.mark.parametrize("name", ["../outside", "other.json.gz", "legacy-production.json.gz/extra"])
def test_backup_name_allowlist(name):
    transport = Transport()
    with pytest.raises(ValueError):
        upload_verified(transport, Lease(), name, b"private-fixture")
    assert not transport.calls


@pytest.mark.parametrize("name", ["legacy-production", "legacy-staging"])
def test_stopped_checkpoint_refuses_running_legacy(monkeypatch, name):
    monkeypatch.setattr(checkpoint_module, "configuration", lambda *a: {"site": {"properties": {"state": "Running"}}})
    monkeypatch.setattr(checkpoint_module, "capture_state", lambda *a: pytest.fail("Must not capture before stop"))
    with pytest.raises(AzureIOError, match="stopped legacy"):
        checkpoint_module.checkpoint(None, Lease(), name, commit="a"*40, version="v1.0.5", stopped=True)


def test_stopped_flag_cannot_relabel_target_backup():
    with pytest.raises(ValueError):
        checkpoint_module.checkpoint(None, None, "target-production", commit="a"*40, version="v2.0.0", stopped=True)
