import importlib
from io import BytesIO

import pytest
from PIL import Image

from src.mcp_delivery import sign_delivery


@pytest.fixture
def security_app(monkeypatch, tmp_path):
    env = {
        "TEST_MODE": "false",
        "DEV_AUTH_BYPASS": "false",
        "STORAGE_MODE": "local",
        "FLASK_SECRET_KEY": "0123456789abcdef0123456789abcdef",
        "MSAL_CLIENT_ID": "dummy-client",
        "MSAL_CLIENT_SECRET": "dummy-secret",
        "MSAL_TENANT_ID": "dummy-tenant",
        "MSAL_REDIRECT_URI": "http://localhost/auth/callback",
        "ANTHROPIC_API_KEY": "dummy-key",
        "MAINTENANCE_ADMIN_USERS": "admin@example.com",
        "IMAGE_FOLDER": str(tmp_path),
        "CORS_ORIGINS": "http://localhost",
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "RATE_LIMIT_AUTH_REQUESTS": "5",
        "RATE_LIMIT_STREAM_REQUESTS": "3",
        "MCP_INTERNAL_SECRET": "test-mcp-secret",
        "APP_STATE_DIR": str(tmp_path),
        "APP_READ_ONLY": "false",
        "INGEST_POLLER_ENABLED": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import src.config as config_module
    import src.app as app_module

    importlib.reload(config_module)
    app_module = importlib.reload(app_module)
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture
def client(security_app):
    return security_app.test_client()


def _login(client, email="user@example.com", csrf_token="test-csrf-token"):
    with client.session_transaction() as sess:
        sess["user"] = {"preferred_username": email}
        sess["_csrf_token"] = csrf_token


def test_read_only_rejects_post_and_legacy_sse_mutations(client, monkeypatch):
    monkeypatch.setenv("APP_READ_ONLY", "true")
    _login(client, email="admin@example.com")
    headers = {"Origin": "http://localhost", "Referer": "http://localhost/maintenance"}
    for path in ["/api/upload/stage", "/run/scan-live"]:
        response = client.post(path, json={}, headers=headers)
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "60"
    for path in ["/api/upload/process", "/api/maintenance/retag-run"]:
        response = client.get(path, query_string={"csrf_token": "test-csrf-token"})
        assert response.status_code == 503
    assert client.get("/health").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/").status_code == 200


def test_deployment_drain_requires_admin_and_same_origin(client):
    path = "/api/maintenance/deployment-drain"
    headers = {"Origin": "http://localhost"}
    assert client.post(path, json={"enabled": True}, headers=headers).status_code == 401
    _login(client)
    assert client.get("/api/maintenance/deployment-status").status_code == 403
    assert client.post(path, json={"enabled": True}, headers=headers).status_code == 403
    _login(client, email="admin@example.com")
    assert client.post(path, json={"enabled": True}).status_code == 403
    assert client.post(path, json=[True], headers=headers).status_code == 400
    response = client.post(path, json={"enabled": True}, headers=headers)
    assert response.json == {"read_only": False, "draining": True, "active_work": 0}
    assert client.post("/run/scan-live", headers=headers).status_code == 503
    assert client.get("/readyz").status_code == 200
    assert client.post(path, json={"enabled": False}, headers=headers).json["draining"] is False


def test_read_only_unknown_get_is_denied_before_handler(security_app, monkeypatch):
    monkeypatch.setenv("APP_READ_ONLY", "true")
    security_app.add_url_rule("/future-job", "future_job", lambda: pytest.fail("Unknown route executed"))
    assert security_app.test_client().get("/future-job").status_code == 503


def test_command_stays_tracked_after_sse_disconnect(security_app, monkeypatch):
    import threading
    from src import app as module
    from src import deployment_controls as controls

    finish = threading.Event()
    threads = []
    class TrackedThread(controls.WorkThread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            threads.append(self)
    class Process:
        returncode = 0
        def __init__(self, *_args, **_kwargs):
            self.stdout = self.lines()
        def lines(self):
            yield "started\n"
            finish.wait(5)
            # Exceed queue capacity after disconnect: reader must not block.
            for _ in range(1000):
                yield "output\n"
        def wait(self):
            finish.wait(5)
            return 0
    monkeypatch.setattr(controls, "WorkThread", TrackedThread)
    monkeypatch.setattr(module.subprocess, "Popen", Process)
    try:
        with security_app.test_request_context("/run/scan-live"):
            response = module._stream_command(["offline-fixture"])
            assert next(response.response) == "data: [START]\n\n"
            response.close()
        assert controls.set_drain(True)["active_work"] == 1
        with pytest.raises(controls.WritesDisabled):
            controls.Work()
    finally:
        finish.set()
        for thread in threads:
            thread.join(5)
        controls.set_drain(False)
    assert not any(thread.is_alive() for thread in threads)
    assert controls.snapshot()["active_work"] == 0


def test_security_headers_present(client):
    response = client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_run_route_requires_admin(client):
    _login(client, email="user@example.com")
    response = client.post(
        "/run/scan-test",
        headers={"Origin": "http://localhost", "Referer": "http://localhost/library"},
    )
    assert response.status_code == 403
    assert b"Admin access required" in response.data


def test_tag_manager_route_redirects_to_maintenance_panel(client):
    _login(client, email="admin@example.com")
    response = client.get("/tag-manager")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/maintenance#tag-manager")


def test_state_change_requires_same_origin_headers(client):
    _login(client)
    response = client.patch("/api/image-status", json={"id": "abc", "status": "approved"})
    assert response.status_code == 403
    assert response.get_json()["error"] == "Invalid request origin"


def test_invalid_upload_rejected(client):
    _login(client)
    response = client.post(
        "/api/upload/stage",
        data={"files": (BytesIO(b"not-an-image"), "fake.png")},
        content_type="multipart/form-data",
        headers={"Origin": "http://localhost", "Referer": "http://localhost/upload"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert "invalid or corrupt image file" in payload["staged"][0]["error"]


def test_stock_search_rate_limited(client):
    _login(client)
    headers = {"Origin": "http://localhost", "Referer": "http://localhost/stock-search"}
    for _ in range(5):
        response = client.post(
            "/api/parse-suggestions",
            json={"content": "Need one image suggestion"},
            headers=headers,
        )
        assert response.status_code == 200

    limited = client.post(
        "/api/parse-suggestions",
        json={"content": "Need one image suggestion"},
        headers=headers,
    )
    assert limited.status_code == 429
    payload = limited.get_json()
    assert payload["error"] == "Rate limit exceeded"
    assert int(limited.headers["Retry-After"]) >= 1


def test_m13_mark_rejects_expected_count_mismatch(client):
    _login(client, email="admin@example.com")
    response = client.post(
        "/api/maintenance/quality-drift-queue/mark",
        json={
            "record_ids": ["rec_1"],
            "expected_count": 2,
            "marker": "?retag-queue",
        },
        headers={"Origin": "http://localhost", "Referer": "http://localhost/maintenance"},
    )
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["error"] == "expected_count does not match record_ids length"


def test_editor_can_patch_focal_point(client, monkeypatch, tmp_path):
    import src.app as app_module
    from src.image_metadata import write_metadata

    _login(client)
    monkeypatch.setattr(
        app_module,
        "get_all_records",
        lambda: [{"id": "rec-1", "fields": {"Slug": "wide-image"}}],
    )
    write_metadata(
        {"slug": "wide-image", "focalPoint": {"x": 0.5, "y": 0.5}},
        storage_mode="local",
        image_folder=str(tmp_path),
    )

    response = client.patch(
        "/api/image/focal-point",
        json={"id": "rec-1", "x": 0.2, "y": 0.75},
        headers={"Origin": "http://localhost", "Referer": "http://localhost/library"},
    )

    assert response.status_code == 200
    assert response.get_json()["focalPoint"] == {"x": 0.2, "y": 0.75}


def test_exact_asset_delivery_preserves_webp_bytes(client, tmp_path):
    content = b"RIFF-test-webp-content"
    asset = tmp_path / "Hero" / "Banners" / "wide-image.webp"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(content)

    response = client.get(
        "/api/mcp/asset",
        query_string={
            "area": "Hero",
            "path": "Banners/wide-image.webp",
            "key": "test-mcp-secret",
        },
    )

    assert response.status_code == 200
    assert response.data == content
    assert response.content_type == "image/webp"


def _write_test_image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 180), color=(20, 90, 140)).save(path, format="WEBP")


def test_mcp_thumbnail_accepts_key_on_browser_get(client, tmp_path):
    _write_test_image(tmp_path / "WebP" / "Community" / "browser-test.webp")

    response = client.get(
        "/api/mcp/thumbnail",
        query_string={"path": "Community/browser-test.webp", "key": "test-mcp-secret"},
        headers={"User-Agent": "Mozilla/5.0"},
    )

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    assert response.data.startswith(b"\xff\xd8")
    assert response.headers["Cache-Control"] == "public, max-age=300"


def test_mcp_thumbnail_accepts_short_lived_signed_url(client, tmp_path):
    location = "Community/signed-test.webp"
    _write_test_image(tmp_path / "WebP" / location)
    signed = sign_delivery(
        "test-mcp-secret",
        "thumbnail",
        location,
        ttl_seconds=300,
    )

    response = client.get(
        "/api/mcp/thumbnail",
        query_string={"path": location, **signed},
        headers={"User-Agent": "Mozilla/5.0"},
    )

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    assert response.headers["Cache-Control"].startswith("public, max-age=")


def test_mcp_thumbnail_rejects_expired_or_tampered_signature(client, tmp_path):
    location = "Community/signed-test.webp"
    _write_test_image(tmp_path / "WebP" / location)
    expired = sign_delivery(
        "test-mcp-secret",
        "thumbnail",
        location,
        ttl_seconds=10,
        now=1,
    )
    valid_for_other_path = sign_delivery(
        "test-mcp-secret",
        "thumbnail",
        "Community/other.webp",
        ttl_seconds=300,
    )

    expired_response = client.get(
        "/api/mcp/thumbnail",
        query_string={"path": location, **expired},
    )
    tampered_response = client.get(
        "/api/mcp/thumbnail",
        query_string={"path": location, **valid_for_other_path},
    )

    assert expired_response.status_code == 401
    assert tampered_response.status_code == 401


def test_mcp_thumbnail_proxies_sharepoint_bytes_without_redirect(client, monkeypatch):
    import src.app as app_module

    buf = BytesIO()
    Image.new("RGB", (320, 180), color=(20, 90, 140)).save(buf, format="WEBP")

    class FakeSharePointClient:
        def get_file_bytes(self, path):
            assert path.endswith("/WebP/Community/browser-test.webp")
            return buf.getvalue()

        def get_thumbnail_url(self, path):
            raise AssertionError("public MCP thumbnails must not redirect to SharePoint")

    monkeypatch.setattr(app_module.Config, "STORAGE_MODE", "sharepoint")
    monkeypatch.setattr(app_module, "get_sp_client", lambda: FakeSharePointClient())

    response = client.get(
        "/api/mcp/thumbnail",
        query_string={"path": "Community/browser-test.webp", "key": "test-mcp-secret"},
        headers={"User-Agent": "Mozilla/5.0"},
    )

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    assert "Location" not in response.headers


def test_selective_backfill_candidate_scan_is_read_only(client, monkeypatch):
    import src.app as app_module

    _login(client, email="admin@example.com")
    monkeypatch.setattr(app_module, "_records_snapshot", lambda use_cache=False: [])

    response = client.get("/api/maintenance/hero-backfill/candidates?status=approved")

    assert response.status_code == 200
    assert response.get_json()["candidateCount"] == 0
    assert response.get_json()["dryRun"] is True


def test_selective_backfill_requires_an_exact_nonempty_selection(client):
    _login(client, email="admin@example.com")
    headers = {"Origin": "http://localhost", "Referer": "http://localhost/maintenance"}

    response = client.post(
        "/api/maintenance/hero-backfill/run",
        json={"record_ids": [], "expected_count": 0},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Select at least one record"
