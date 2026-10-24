from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time

import pytest
import requests

from src.graph_reads import GraphReads
from src.sharepoint_client import SharePointClient
from src.sharepoint_list_client import SharePointListClient


URL = "https://graph.microsoft.com/v1.0/drives/test/items"


class Response:
    def __init__(self, status=200, after=None):
        self.status_code, self.headers, self.closed = status, {}, False
        if after is not None: self.headers["Retry-After"] = after
    def close(self): self.closed = True


class Session:
    def __init__(self, responses=None):
        self.responses, self.calls, self.mounts = list(responses or []), [], []
        self.cookies = SimpleNamespace(clear=lambda: None)
    def mount(self, *args): self.mounts.append(args)
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        reply = self.responses.pop(0) if self.responses else Response()
        if isinstance(reply, Exception): raise reply
        return reply
    def close(self): pass


def test_session_reused_in_thread_not_shared_across_threads():
    sessions = []
    def factory():
        value = Session(); sessions.append(value); return value
    client = GraphReads(factory=factory)
    client.get(URL, headers={"Authorization": "private"})
    client.get(URL, headers={"Authorization": "new-private"})
    assert len(sessions) == 1 and len(sessions[0].calls) == 2
    assert sessions[0].trust_env is False
    assert sessions[0].mounts[0][1].max_retries.total == 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(client.get, URL, headers={}).result(timeout=3)
    assert len(sessions) == 2
    assert all(call[1]["allow_redirects"] is False for session in sessions for call in session.calls)


def test_only_one_safe_retry_within_deadline():
    first = Response(429, "1")
    session, now, pauses = Session([first, Response(503)]), [0], []
    def pause(seconds): now[0] += seconds; pauses.append(seconds)
    client = GraphReads(factory=lambda: session, clock=lambda: now[0], pause=pause)
    assert client.get(URL, headers={}, timeout=3).status_code == 503
    assert len(session.calls) == 2 and first.closed
    assert pauses == [1]
    assert session.calls[1][1]["timeout"] == 2


@pytest.mark.parametrize("after", ["120", "nonsense", "-1", "999999999999999999999"])
def test_long_invalid_retry_after_never_shortened(after):
    session = Session([Response(429, after)])
    client = GraphReads(factory=lambda: session, pause=lambda _: pytest.fail("must not wait/retry"))
    assert client.get(URL, headers={}).status_code == 429
    assert len(session.calls) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 302, 500])
def test_other_statuses_are_not_retried(status):
    session = Session([Response(status)])
    assert GraphReads(factory=lambda: session).get(URL, headers={}).status_code == status
    assert len(session.calls) == 1


def test_transport_errors_not_retried_and_no_mutation_interface():
    session = Session([requests.ConnectionError("fixture")])
    client = GraphReads(factory=lambda: session)
    with pytest.raises(requests.ConnectionError): client.get(URL, headers={})
    assert len(session.calls) == 1
    assert not any(hasattr(client, name) for name in ("post", "put", "patch", "delete", "request"))


@pytest.mark.parametrize("url", ["https://other.test/v1.0/", "http://graph.microsoft.com/v1.0/drives", "https://graph.microsoft.com@other.test/v1.0/items"])
def test_unapproved_hosts_rejected_before_session_creation(url):
    client = GraphReads(factory=lambda: pytest.fail("must not create session"))
    with pytest.raises(ValueError): client.get(url, headers={})


def test_token_refresh_is_serialized_without_replaying_post(monkeypatch):
    client, calls = SharePointClient(), []
    def post(*_args, **_kwargs):
        calls.append(1)
        time.sleep(0.01)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"access_token": "fixture-token", "expires_in": 3600})
    monkeypatch.setattr(requests, "post", post)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: client._get_token(), range(5)))
    assert results == ["fixture-token"] * 5 and calls == [1]


def test_list_reads_use_pool_but_writes_keep_single_attempt(monkeypatch):
    monkeypatch.setenv("APP_READ_ONLY", "false")
    client, reads, writes = SharePointListClient(), [], []
    monkeypatch.setattr(client, "_headers", lambda: {"Authorization": "fixture"})
    def get(*args, **kwargs):
        reads.append(1)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"value": []})
    client._reads = SimpleNamespace(get=get)
    monkeypatch.setattr(requests, "patch", lambda *a, **k: writes.append(1) or SimpleNamespace(raise_for_status=lambda: None))
    assert client.get_all_records() == []
    assert client.patch_fields("1", {"Status": "approved"}) is True
    assert reads == [1] and writes == [1]
