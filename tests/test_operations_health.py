import json
from types import SimpleNamespace

import pytest

from scripts import operations_health as health

COMMIT, BUILD = "a" * 40, "100-1"


class Reply:
    def __init__(self, body, status=200, content_type="application/json"):
        self.body, self.status_code = body, status
        self.headers = {"Content-Type": content_type}
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def iter_content(self, _): yield json.dumps(self.body).encode()


def fixture():
    replies = [Reply({"status": "ok"}), Reply({"status": "ready", "telemetry": True,
        "commit": COMMIT, "build_id": BUILD, "version": "v2.0.0"}),
        Reply({"commit": COMMIT, "build_id": BUILD, "version": "v2.0.0"}),
        Reply({"error": "Authentication required"}, 401)]
    calls, closed = [], []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return replies[len(calls) - 1]
    return SimpleNamespace(get=get, close=lambda: closed.append(True), replies=replies, calls=calls,
        closed=closed, cookies=SimpleNamespace(clear=lambda: None))


def test_four_fixed_read_only_requests_and_no_credentials():
    client = fixture()
    report = health.check(COMMIT, BUILD, session=client)
    assert report["status"] == "passed" and len(report["checks"]) == 4
    assert len(client.calls) == 4 and client.closed == [True] and client.trust_env is False
    for url, kwargs in client.calls:
        assert url.startswith(health.ORIGIN + "/")
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] <= 10
        assert set(kwargs["headers"]) == {"Accept", "Cache-Control"}
    assert "authenticated_catalog" in report["not_assessed"]


@pytest.mark.parametrize("index,body,status,content_type", [
    (0, {"status": "bad"}, 200, "application/json"),
    (1, {"status": "ready"}, 200, "application/json"),
    (2, {"commit": COMMIT, "build_id": "999-1", "version": "v2.0.0"}, 200, "application/json"),
    (3, {"error": "Authentication required"}, 200, "application/json"),
    (3, {}, 403, "application/json"), (0, {}, 302, "text/html"),
    (0, {"status": "ok"}, 200, "text/html"), (0, [], 200, "application/json")])
def test_failed_contract_stops_without_retry(index, body, status, content_type):
    client = fixture(); client.replies[index] = Reply(body, status, content_type)
    report = health.check(COMMIT, BUILD, session=client)
    assert report["status"] == "failed" and len(client.calls) == index + 1


def test_network_errors_and_response_limits_do_not_leak_details():
    for fail in (False, True):
        client = fixture()
        client.replies[0] = Reply({"private": "SECRET" * health.MAX_BYTES})
        if fail:
            def get(*a, **k): raise RuntimeError("SECRET credentials")
            client.get = get
        report = health.check(COMMIT, BUILD, session=client)
        assert report["status"] == "failed" and "SECRET" not in json.dumps(report)
        assert client.closed == [True]


def test_expired_budget_is_incomplete_without_request():
    client = fixture(); ticks = iter([0, 31])
    report = health.check(COMMIT, BUILD, session=client, clock=lambda: next(ticks))
    assert report["status"] == "incomplete" and not client.calls


@pytest.mark.parametrize("commit,build", [("main", BUILD), (COMMIT, "unreviewed"), (COMMIT, "100-0")])
def test_release_identity_required_before_network(commit, build):
    client = fixture()
    with pytest.raises(ValueError): health.check(commit, build, session=client)
    assert not client.calls


def test_cli_disabled_by_default(monkeypatch, capsys):
    monkeypatch.delenv("IMAGE_LIBRARY_PUBLIC_CHECKS_ENABLED", raising=False)
    monkeypatch.setattr(health, "check", lambda *a: pytest.fail("Disabled must not probe"))
    assert health.main(["--commit", COMMIT, "--build-id", BUILD]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "configuration_required"


def test_cli_explicit_enable_restores_alarm(monkeypatch, capsys):
    monkeypatch.setenv("IMAGE_LIBRARY_PUBLIC_CHECKS_ENABLED", "true")
    monkeypatch.setattr(health, "check", lambda *a: {"status": "passed"})
    assert health.main(["--commit", COMMIT, "--build-id", BUILD]) == 0
    assert health.signal.getitimer(health.signal.ITIMER_REAL)[0] == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
