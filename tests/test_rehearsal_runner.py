import json
from types import SimpleNamespace

import pytest

from scripts import rehearsal_runner as rehearsal
from scripts import release_azure_io as azure


@pytest.mark.parametrize("method,url", [
    ("PUT", azure.ARM + azure.APP_ID + "/sitecontainers/main?api-version=x"),
    ("POST", azure.ARM + azure.APP_ID + "/stop?api-version=x"),
    ("GET", azure.SCM["production"] + "/api/vfs/"),
    ("GET", azure.SCM["staging"] + "/api/vfs/"),
    ("GET", azure.STORAGE + "/rollback-backups/private"),
    ("PUT", azure.STORAGE + "/release-control/production.json?comp=lease"),
    ("PUT", azure.ARM + rehearsal.target.APP_ID + "/config/appsettings?api-version=x"),
    ("POST", rehearsal.target.SCM + "/api/command"),
    ("DELETE", azure.ARM + rehearsal.target.APP_ID + "?api-version=x"),
])
def test_physical_fence_blocks_live_targets_and_unneeded_rehearsal_writes(method, url):
    identity = SimpleNamespace(token=lambda _: pytest.fail("Must reject before credentials"))
    with pytest.raises(azure.AzureIOError):
        rehearsal.IsolatedTransport(identity=identity).request(method, url)


def test_runner_refuses_unapproved_context_before_network(monkeypatch):
    monkeypatch.delenv("IMAGE_LIBRARY_RECOVERY_REHEARSAL_ENABLED", raising=False)
    monkeypatch.setattr(rehearsal, "GitHubReads", lambda _: pytest.fail("No network permitted"))
    with pytest.raises(azure.AzureIOError): rehearsal.execute()


@pytest.mark.parametrize("key,value", [("authType", "UserCredentials"), ("isMain", False),
    ("targetPort", "80"), ("startUpCommand", "override"), ("environmentVariables", [{"name": "bad"}])])
def test_container_execution_overrides_rejected(key, value):
    props = {"image": rehearsal.target.PRIOR_IMAGE, "authType": "SystemIdentity", "isMain": True, "targetPort": "8080"}
    props[key] = value
    with pytest.raises(azure.AzureIOError): rehearsal.immutable_container({"properties": props})


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self.raw = SimpleNamespace(read=lambda *args, **kwargs: json.dumps(body).encode())

    def __enter__(self): return self
    def __exit__(self, *args): pass


class Session:
    def __init__(self, responses): self.responses = iter(responses)
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get(self, *args, **kwargs):
        value = next(self.responses)
        if isinstance(value, Exception): raise value
        return value


def test_normal_readiness_does_not_ignore_access_denial(monkeypatch):
    monkeypatch.setattr(rehearsal.requests, "Session", lambda: Session([Response(403)]))
    with pytest.raises(azure.AzureIOError, match="HTTP 403"):
        rehearsal.ready({})


def test_explicit_cold_start_polls_but_still_requires_exact_ready_identity(monkeypatch):
    receipt = {"commit": "a" * 40, "build_id": "100-1"}
    body = dict(receipt, status="ready", version="v2.0.0")
    monkeypatch.setattr(rehearsal.requests, "Session", lambda: Session([Response(403), Response(200, body)]))
    pauses = []
    monkeypatch.setattr(rehearsal.time, "sleep", pauses.append)
    assert rehearsal.ready(receipt, cold_start=True) == body
    assert pauses == [3]


def test_cold_start_access_denial_is_bounded_not_success(monkeypatch):
    monkeypatch.setattr(rehearsal.requests, "Session", lambda: Session([Response(403)]))
    ticks = iter([0, 0, 301])
    monkeypatch.setattr(rehearsal.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(rehearsal.time, "sleep", lambda _: None)
    with pytest.raises(azure.AzureIOError, match="Exact rehearsal readiness missing"):
        rehearsal.ready({}, cold_start=True)


@pytest.mark.parametrize("error", [rehearsal.requests.ReadTimeout(), rehearsal.requests.ConnectionError()])
def test_readiness_transport_transients_retry_only_get(monkeypatch, error):
    receipt = {"commit": "a" * 40, "build_id": "100-1"}
    body = dict(receipt, status="ready", version="v2.0.0")
    monkeypatch.setattr(rehearsal.requests, "Session", lambda: Session([error, Response(200, body)]))
    pauses = []
    monkeypatch.setattr(rehearsal.time, "sleep", pauses.append)
    assert rehearsal.ready(receipt) == body
    assert pauses == [3]
