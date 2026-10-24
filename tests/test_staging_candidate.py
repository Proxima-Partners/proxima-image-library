from types import SimpleNamespace

import pytest

from scripts import staging_candidate as staging
from scripts.release_azure_io import AzureIOError
from test_production_azure_adapter import receipt


@pytest.mark.parametrize("method,url", [
    ("PUT", staging.ARM + staging.APP_ID + "/sitecontainers/main?api-version=x"),
    ("POST", staging.ARM + staging.APP_ID + "/stop?api-version=x"),
    ("POST", staging.ARM + staging.APP_ID + "/start?api-version=x"),
    ("PUT", staging.ARM + staging.STAGING_ID + "/config/appsettings?api-version=x"),
    ("PUT", staging.ARM + staging.STAGING_ID + "/config/web?api-version=x"),
    ("PUT", staging.SCM["production"] + "/api/vfs/.image-library-release-control/request.json"),
    ("POST", staging.SCM["production"] + "/api/command"),
    ("POST", staging.SCM["staging"] + "/api/command"),
    ("DELETE", staging.SCM["staging"] + "/api/vfs/proxima_ss_counter.json"),
    ("DELETE", staging.STORAGE + "/rollback-backups/owned/staging.json.gz"),
])
def test_physical_write_fence_before_credentials(method, url):
    identity = SimpleNamespace(token=lambda _: pytest.fail("No credentials for rejected operation"))
    with pytest.raises(AzureIOError): staging.StagingTransport(identity=identity).request(method, url)


@pytest.mark.parametrize("fault", [None, "stop", "cleanup", "put", "start", "ready", "inventory"])
@pytest.mark.parametrize("error", [AzureIOError, KeyboardInterrupt])
def test_cold_staging_update_order_and_terminal_failure(fault, error, monkeypatch):
    events = []
    def event(name, result=None):
        events.append(name)
        if name == fault: raise error("uncertain")
        return result
    candidate = receipt("b", "124-1")
    life = SimpleNamespace(stop=lambda: event("stop", {"old"}), start=lambda: event("start"),
                           inventory=lambda: event("inventory", {"new"}))
    lease = SimpleNamespace(checkpoint=lambda _: event("checkpoint"))
    def put(method, url, **kwargs):
        assert method == "PUT" and url == staging.ARM + staging.STAGING_ID + "/sitecontainers/main?api-version=" + staging.API
        return event("put", (200, {}, b'{"properties":{"provisioningState":"Succeeded"}}'))
    adapter = SimpleNamespace(receipts={candidate["registry_image"]:candidate}, lifecycles={"staging":life},
        lease=lease, transport=SimpleNamespace(request=put),
        cleanup_channel=lambda slot:event("cleanup"), _assert_channel_absent=lambda slot:event("absent"),
        _config=lambda slot:({}, {}, {}, {"name":"main", "properties":{"image":"prior"}}),
        _wait_cold_readiness=lambda *args, **kwargs:event("ready"))
    unchanged = lambda image:event("guard")
    monkeypatch.setattr(staging, "wait_readiness", lambda *args:event("ready"))
    if fault:
        with pytest.raises(error): staging.cold_update(adapter, candidate, "prior", unchanged)
        assert events[-1] == fault and events.count(fault) == 1
    else:
        result=staging.cold_update(adapter,candidate,"prior",unchanged)
        assert result["fresh_named_runtime"] is True
        assert events == ["guard","stop","guard","cleanup","absent","guard","checkpoint","put",
                          "guard","start","ready","inventory","guard"]


@pytest.mark.parametrize("code", [403, 502, 503])
def test_staging_startup_transient_requires_exact_ready_and_never_mutates(monkeypatch, code):
    from test_rehearsal_runner import Response, Session
    candidate = receipt("b", "124-1")
    ready = dict(candidate, version="v2.0.0", telemetry=True, status="ready")
    session = Session([Response(code), Response(200, ready)])
    monkeypatch.setattr(staging.requests, "Session", lambda: session)
    sleeps = []
    monkeypatch.setattr(staging.time, "sleep", sleeps.append)
    staging.wait_readiness(SimpleNamespace(assert_lease=lambda:None),candidate,staging.time.time()+20)
    assert sleeps == [3]


@pytest.mark.parametrize("code", [401, 404, 302])
def test_other_staging_access_failures_are_terminal(monkeypatch, code):
    from test_rehearsal_runner import Response, Session
    monkeypatch.setattr(staging.requests, "Session", lambda: Session([Response(code)]))
    with pytest.raises(AzureIOError):
        staging.wait_readiness(SimpleNamespace(assert_lease=lambda:None),receipt(),staging.time.time()+20)


def test_staging_403_never_counts_as_success(monkeypatch):
    from test_rehearsal_runner import Response, Session
    monkeypatch.setattr(staging.requests, "Session", lambda:Session([Response(403)]))
    ticks=iter([0, 0, 0, 301])
    monkeypatch.setattr(staging.time, "time", lambda:next(ticks))
    monkeypatch.setattr(staging.time, "sleep", lambda _:None)
    with pytest.raises(AzureIOError,match="unconfirmed"):
        staging.wait_readiness(SimpleNamespace(assert_lease=lambda:None),receipt(),300)
