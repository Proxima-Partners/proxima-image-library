import json
import stat
from types import SimpleNamespace

import pytest

from scripts import release_azure_io as io


class Response:
    def __init__(self, status=200, body=b"{}", headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def iter_content(self, size):
        yield self.body


class Session:
    def __init__(self, response=None, failure=None):
        self.response, self.failure, self.calls = response or Response(), failure, []
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.failure:
            raise self.failure
        return self.response


def transport(session=None):
    return io.AzureTransport(SimpleNamespace(token=lambda audience: "PRIVATE-token-fixture"), session or Session())


@pytest.mark.parametrize("url", [
    "http://management.azure.com/x", "https://example.com/x",
    "https://management.azure.com.evil.test/x", "https://user@management.azure.com/x",
    io.ARM + "/../x", io.ARM + "/%2e%2e/x", io.ARM + "/%252e%252e/x",
    io.ARM + "/%5cx", io.ARM + "/x#fragment", io.ARM + "/x\n",
])
def test_host_and_path_restrictions_before_auth(url):
    session = Session()
    with pytest.raises(io.AzureIOError):
        transport(session).request("GET", url)
    assert session.calls == []


def test_auth_override_forbidden():
    with pytest.raises(io.AzureIOError):
        transport().request("GET", io.ARM + "/", headers={"authorization": "other"})


def test_bearer_only_no_redirects_or_proxies_and_storage_date():
    session = Session()
    transport(session).request("GET", io.STORAGE + "/release-control/production.json")
    _, arguments = session.calls[0]
    assert arguments["headers"]["Authorization"] == "Bearer PRIVATE-token-fixture"
    assert arguments["headers"]["x-ms-date"]
    assert arguments["allow_redirects"] is False and session.trust_env is False


@pytest.mark.parametrize("status", [301, 302, 401, 403, 409, 500])
def test_refusal_does_not_expose_body_or_retry(status):
    session = Session(Response(status, b"SECRET"))
    with pytest.raises(io.AzureIOError) as error:
        transport(session).request("PUT", io.ARM + "/")
    assert "SECRET" not in str(error.value) and len(session.calls) == 1


def test_network_exception_redacted_and_not_retried():
    session = Session(failure=RuntimeError("SECRET"))
    with pytest.raises(io.AzureIOError, match="outcome unknown") as error:
        transport(session).request("PUT", io.ARM + "/")
    assert "SECRET" not in str(error.value) and len(session.calls) == 1


def test_bounded_json_response():
    with pytest.raises(io.AzureIOError, match="bounded size"):
        transport(Session(Response(body=b"1234"))).request("GET", io.ARM + "/", max_bytes=3)
    with pytest.raises(io.AzureIOError, match="Invalid Azure JSON"):
        transport(Session(Response(body=b"bad"))).json("GET", io.ARM + "/")


def test_cli_identity_subscription_audience_cache_and_errors(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"subscription": io.SUB,
            "accessToken": "PRIVATE", "expires_on": 9999999999}))
    monkeypatch.setattr(io.subprocess, "run", run)
    identity = io.AzureCLIIdentity()
    assert identity.token(io.ARM_AUDIENCE) == "PRIVATE"
    assert identity.token(io.ARM_AUDIENCE) == "PRIVATE" and len(calls) == 1
    assert "--subscription" in calls[0] and io.SUB in calls[0]
    with pytest.raises(io.AzureIOError):
        identity.token("https://unapproved.example/")
    monkeypatch.setattr(io.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="SECRET"))
    with pytest.raises(io.AzureIOError) as error:
        io.AzureCLIIdentity().token(io.ARM_AUDIENCE)
    assert "SECRET" not in str(error.value)


class LeaseTransport:
    def __init__(self):
        self.calls, self.owner, self.exists, self.fail_phase = [], None, False, None
    def request(self, method, url, *, accepted=(200,), headers=None, data=None, **kwargs):
        self.calls.append((method, url, headers))
        action = headers.get("x-ms-lease-action")
        if action == self.fail_phase and self.fail_phase is not None:
            raise io.AzureIOError("Ambiguous")
        if action == "acquire":
            if self.owner:
                raise io.AzureIOError("Conflict")
            self.owner = headers["x-ms-proposed-lease-id"]
            return 201, {"x-ms-lease-id": self.owner}, b""
        if action in {"renew", "release"}:
            if headers["x-ms-lease-id"] != self.owner:
                raise io.AzureIOError("Wrong owner")
            if action == "release":
                self.owner = None
            return 200, {}, b""
        if headers.get("If-None-Match") == "*":
            status = 412 if self.exists else 201
            self.exists = True
            return status, {}, b""
        assert headers.get("x-ms-lease-id") == self.owner
        return 201, {}, b""


def test_lease_initialize_never_overwrites_and_excludes_contender(tmp_path):
    fake = LeaseTransport()
    lease = io.BlobReleaseLease(fake, tmp_path / "recovery.json", blob="rehearsal.json")
    assert lease.initialize() is True and lease.initialize() is False
    with lease.exclusive(io.APP_ID):
        assert fake.owner == lease.lease_id
        contender = io.BlobReleaseLease(fake, tmp_path / "contender.json", blob="rehearsal.json")
        with pytest.raises(io.AzureIOError, match="Conflict"):
            contender.acquire()
        lease.assert_held()
    assert fake.owner is None and not lease.acquired
    assert stat.S_IMODE((tmp_path / "recovery.json").stat().st_mode) == 0o600
    assert all(call[2].get("x-ms-lease-action") != "break" for call in fake.calls)


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_exception_keeps_infinite_lease_for_reconciliation(tmp_path, failure):
    fake = LeaseTransport()
    lease = io.BlobReleaseLease(fake, tmp_path / "recovery.json")
    with pytest.raises(failure):
        with lease.exclusive(io.APP_ID):
            raise failure()
    assert fake.owner == lease.lease_id
    assert not any(call[2].get("x-ms-lease-action") == "release" for call in fake.calls)


def test_recovery_file_cannot_be_reused_and_resource_is_exact(tmp_path):
    fake = LeaseTransport()
    path = tmp_path / "recovery.json"
    path.write_text("prior")
    lease = io.BlobReleaseLease(fake, path)
    with pytest.raises(FileExistsError):
        lease.acquire()
    assert fake.calls == []
    with pytest.raises(io.AzureIOError):
        with lease.exclusive("other-resource"):
            pass
    with pytest.raises(ValueError):
        io.BlobReleaseLease(fake, path, blob="unapproved.json")


def test_recovery_directory_fsync_precedes_cloud_mutation(tmp_path, monkeypatch):
    fake = LeaseTransport()
    def fail(_):
        raise OSError("durability failure")
    monkeypatch.setattr(io.os, "fsync", fail)
    with pytest.raises(OSError):
        io.BlobReleaseLease(fake, tmp_path / "recovery.json").acquire()
    assert fake.calls == []


def test_scm_command_uses_one_kudu_double_quoted_argument():
    import shlex
    import subprocess
    import sys
    from scripts.release_azure_io import scm_python_command
    source = b"print('safe-fixture')\n"
    command = scm_python_command(source)
    assert command.startswith('python3 -c "') and command.endswith('"')
    assert command.count('"') == 2
    arguments = shlex.split(command)
    assert len(arguments) == 3
    result = subprocess.run([sys.executable, *arguments[1:]], capture_output=True, check=True)
    assert result.stdout == b"safe-fixture\n"
