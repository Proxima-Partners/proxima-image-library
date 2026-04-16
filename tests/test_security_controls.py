import importlib
from io import BytesIO

import pytest


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
