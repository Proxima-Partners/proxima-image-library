from io import BytesIO
import json
from types import SimpleNamespace

from PIL import Image
import pytest
import requests

from src.library_diagnostics import Budget, DiagnosticStop, Limits, ReadOnlyGraph, scan
from scripts.library_health_check import main


class Response:
    def __init__(self, data=b"", status=200, headers=None):
        self.data = json.dumps(data).encode() if isinstance(data, dict) else data
        self.status_code, self.headers = status, headers or {}
        self.closed = False

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.closed = True
    def iter_content(self, size):
        for pos in range(0, len(self.data), size):
            yield self.data[pos:pos + size]


class Session:
    def __init__(self, replies):
        self.replies, self.calls = iter(replies), []
        self.cookies = SimpleNamespace(clear=lambda: None)
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.replies)
        if isinstance(response, Exception): raise response
        return response
    def close(self): pass


def client(replies, **limits):
    budget = Budget(Limits(**limits))
    session = Session(replies)
    return ReadOnlyGraph("PRIVATE-token", "site", "Assets", "drive", budget, session), budget, session


def record(number=1):
    return {"id": str(number), "fields": {"Filename": "PRIVATE-filename", "Location": "private.webp",
                                           "High-Res Location": "private.png", "Status": "approved"}}


class Fixture:
    def __init__(self, count=1, failure=None):
        self.count, self.failure, self.samples = count, failure, 0
    def records(self): return (record(i) for i in range(self.count))
    def inventory(self, root, kind):
        if self.failure: raise self.failure
        return iter([("private.webp" if kind == "WebP" else "private.png", "PRIVATE-id")])
    def thumbnail(self, identity):
        self.samples += 1
        return "ok"


def test_complete_report_reuses_metadata_logic_without_private_values():
    fixture = Fixture()
    report = scan(fixture, "Images", Budget(Limits()))
    assert report["status"] == "complete"
    assert report["references"] == dict(status="observed", missing_webp=0, missing_original=0, orphan_webp=0, orphan_original=0)
    assert report["catalog"]["metadata_missing"]["missing_alt"] == 1
    assert report["thumbnails"]["checked"] == 1
    assert "PRIVATE" not in json.dumps(report) and "private." not in json.dumps(report)


@pytest.mark.parametrize("reason", ["page_limit", "request_limit", "file_limit", "folder_limit", "byte_limit", "time_limit"])
def test_incomplete_inventory_never_claims_missing_or_orphan_files(reason):
    report = scan(Fixture(failure=DiagnosticStop(reason)), "Images", Budget(Limits()))
    assert report["status"] == "incomplete"
    assert report["references"]["status"] == "unknown"
    assert all(v is None for k, v in report["references"].items() if k != "status")
    assert report["thumbnails"]["checked"] == 0


def test_record_limit_stops_iteration_and_never_starts_inventory():
    report = scan(Fixture(count=3), "Images", Budget(Limits(records=2)))
    assert report["status"] == "incomplete" and report["reasons"] == ["record_limit"]
    assert report["catalog"] == {"complete": False, "records": 2}
    assert report["inventory"]["files"] == 0


def test_file_limit_and_disabled_thumbnail_sample():
    report = scan(Fixture(), "Images", Budget(Limits(files=1)))
    assert report["reasons"] == ["file_limit"]
    assert report["references"]["missing_original"] is None
    fixture = Fixture()
    assert scan(fixture, "Images", Budget(Limits(thumbnails=0)))["status"] == "complete"
    assert fixture.samples == 0


def test_provider_exception_is_redacted():
    report = scan(Fixture(failure=RuntimeError("PRIVATE-token-file-url")), "Images", Budget(Limits()))
    assert report["status"] == "failed" and report["reasons"] == ["diagnostic_error"]
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("key,value", [("records", 1001), ("pages", 41), ("seconds", 301),
    ("thumbnails", 21), ("requests", 121), ("total_bytes", 0), ("files", True), ("seconds", 0)])
def test_limits_cannot_be_silently_disabled(key, value):
    with pytest.raises(ValueError): Limits(**{key: value})


def test_request_page_and_byte_limits_apply_before_further_network_reads():
    graph, budget, session = client([Response({"value": [], "@odata.nextLink": "https://graph.microsoft.com/v1.0/sites/site/lists/Assets/items?page=2"})], pages=1)
    with pytest.raises(DiagnosticStop, match="page_limit"): list(graph.records())
    assert len(session.calls) == 1
    graph, budget, session = client([Response(b"12345")], requests=1, response_bytes=4)
    with pytest.raises(DiagnosticStop, match="response_size_limit"): graph._get(graph.list_url)
    with pytest.raises(DiagnosticStop, match="request_limit"): graph._get(graph.list_url)
    assert len(session.calls) == 1
    graph, budget, session = client([Response(b"12345")], total_bytes=4)
    with pytest.raises(DiagnosticStop, match="byte_limit"): graph._get(graph.list_url)


def test_deadline_before_and_during_stream():
    now = [0]
    budget = Budget(Limits(seconds=1), clock=lambda: now[0])
    now[0] = 1
    with pytest.raises(DiagnosticStop, match="time_limit"): budget.request()
    assert budget.requests == 0
    graph, budget, session = client([])
    budget.started = budget.clock() - 301
    with pytest.raises(DiagnosticStop, match="time_limit"): graph._get(graph.list_url)
    assert not session.calls


@pytest.mark.parametrize("url", ["https://evil.test/", "http://graph.microsoft.com/v1.0/", "https://graph.microsoft.com/v1.0/drives/other/items",
    "https://graph.microsoft.com/v1.0/drives/drive/../../sites/other", "https://graph.microsoft.com/v1.0/drives/drive/%2e%2e/other"])
def test_credentials_never_sent_outside_allowlisted_graph_resource(url):
    graph, _, session = client([])
    with pytest.raises(DiagnosticStop, match="unsafe_read_url"): graph._get(url)
    assert session.calls == []


@pytest.mark.parametrize("status,reason", [(401, "authentication_denied"), (403, "authentication_denied"),
    (429, "provider_throttled"), (500, "provider_read_failed"), (302, "provider_read_failed")])
def test_errors_no_retry_no_response_body_leak(status, reason):
    graph, _, session = client([Response(b"PRIVATE-response", status)])
    with pytest.raises(DiagnosticStop, match=reason): graph._get(graph.list_url)
    assert len(session.calls) == 1
    assert session.calls[0][1]["allow_redirects"] is False


def test_thumbnail_redirect_drops_credentials_and_verifies_actual_image():
    image = BytesIO()
    Image.new("RGB", (12, 10), "blue").save(image, "JPEG")
    graph, _, session = client([Response(status=302, headers={"Location": "https://tenant.sharepoint.com/thumb"}), Response(image.getvalue())])
    assert graph.thumbnail("item") == "ok"
    assert "Authorization" in session.calls[0][1]["headers"]
    assert "Authorization" not in session.calls[1][1]["headers"]
    graph, _, session = client([Response(status=302, headers={"Location": "http://127.0.0.1/private"})])
    with pytest.raises(DiagnosticStop, match="unsafe_read_url"): graph.thumbnail("item")
    assert len(session.calls) == 1


def test_malformed_and_cross_collection_pagination_fail_closed():
    for reply in [b"not-json", {"value": "wrong"}, {"value": [], "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/drive/root/children"}]:
        graph, _, _ = client([Response(reply)])
        with pytest.raises(DiagnosticStop, match="invalid_provider_response"): list(graph.records())


def test_pagination_cycle_is_rejected():
    url = "https://graph.microsoft.com/v1.0/sites/site/lists/Assets/items?$expand=fields&$top=100"
    graph, _, session = client([Response({"value": [], "@odata.nextLink": url})])
    with pytest.raises(DiagnosticStop, match="pagination_cycle"): list(graph.records())
    assert len(session.calls) == 1


def test_folder_traversal_is_bounded_before_more_network_calls():
    graph, _, session = client([Response({"value": [{"id": "folder", "name": "child", "folder": {}}]})], folders=1)
    with pytest.raises(DiagnosticStop, match="folder_limit"): list(graph.inventory("Images", "WebP"))
    assert len(session.calls) == 1


def test_network_exception_is_sanitized():
    graph, _, _ = client([requests.ConnectionError("PRIVATE-token")])
    with pytest.raises(DiagnosticStop, match="^provider_read_failed$"): graph._get(graph.list_url)


def test_cli_disabled_by_default_without_touching_network(monkeypatch, capsys):
    monkeypatch.delenv("IMAGE_LIBRARY_DIAGNOSTICS_ENABLED", raising=False)
    monkeypatch.setattr(requests.Session, "get", lambda *_a, **_k: pytest.fail("network forbidden"))
    assert main([]) == 1
    assert json.loads(capsys.readouterr().out)["reasons"] == ["configuration_required"]
