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


@pytest.mark.parametrize("ok", [True, False])
def test_one_shot_control_verifies_retirement_and_cleans_response(ok):
    files, calls = {}, []
    def request(method, url, **kwargs):
        calls.append((method, url))
        if method == "PUT":
            payload = json.loads(kwargs["data"])
            assert payload["protocol"] == 2 and kwargs["headers"] == {"If-None-Match": "*"}
            files[rehearsal.CONTROL + "response.json"] = json.dumps(dict(payload,
                ok=ok, slot="production", workers=1, active_work=0, read_only=False,
                at=int(rehearsal.time.time()), request_retired=True)).encode()
            return 201, {}, b""
        if method == "DELETE":
            assert kwargs["headers"] == {"If-Match": '"owned"'}
            del files[url]
            return 204, {}, b""
        assert method == "GET"
        code = 200 if url in files else 404
        assert code in kwargs["accepted"]
        return code, {"etag": '"owned"'}, files.get(url, b"")
    io = SimpleNamespace(request=request)
    lease = SimpleNamespace(assert_held=lambda: None, checkpoint=lambda _: None)
    assert rehearsal.control(io, lease, "resume", set(), expected={}, ok=ok, protocol=2)["ok"] is ok
    assert files == {}
    assert len([c for c in calls if c[0] == "PUT"]) == 1
    assert len([c for c in calls if c[0] == "DELETE"]) == 1


def test_one_shot_rejects_existing_request_without_mutation():
    calls = []
    def request(method, url, **kwargs):
        calls.append(method)
        return 200, {"etag": "existing"}, b'{"nonce":"old"}'
    lease = SimpleNamespace(assert_held=lambda: None)
    with pytest.raises(azure.AzureIOError):
        rehearsal.control(SimpleNamespace(request=request), lease, "status", {"old"}, protocol=2)
    assert calls == ["GET"]


@pytest.mark.parametrize("fault", ["stop", "delete", "start"])
def test_cleanup_restart_fault_does_not_replay_or_continue(monkeypatch, fault):
    events = []
    def event(name):
        events.append(name)
        if name == fault: raise azure.AzureIOError("unknown mutation outcome")
    monkeypatch.setattr(rehearsal, "configuration", lambda _: {})
    def arm(io, suffix="", **kwargs):
        if suffix == "/start": event("start")
        return {"properties": {"image": "candidate"}}
    monkeypatch.setattr(rehearsal, "arm", arm)
    monkeypatch.setattr(rehearsal.lifecycle, "inventory", lambda _: {"old"})
    monkeypatch.setattr(rehearsal.lifecycle, "stop", lambda *args: event("stop"))
    monkeypatch.setattr(rehearsal.lifecycle, "confirm_stopped", lambda *args: None)
    monkeypatch.setattr(rehearsal, "ready", lambda *args, **kwargs: pytest.fail("No readiness after uncertainty"))
    files = {rehearsal.CONTROL + n: b'{"nonce":"owned"}' for n in ("request.json", "response.json")}
    def request(method, url, **kwargs):
        if url == rehearsal.FIXTURE: return 200, {}, rehearsal.FIXTURE_BYTES
        if method == "DELETE":
            event("delete")
            del files[url]
            return 204, {}, b""
        return (200, {"etag": "owned"}, files[url]) if url in files else (404, {}, b"")
    lease = SimpleNamespace(assert_held=lambda: None, checkpoint=lambda _: None)
    with pytest.raises(azure.AzureIOError):
        rehearsal.cleanup_restart(SimpleNamespace(request=request), lease,
                                  {"registry_image": "candidate"}, {"owned"}, {})
    assert events[-1] == fault and events.count(fault) == 1
