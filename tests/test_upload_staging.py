import importlib

import pytest


@pytest.fixture
def app_module(monkeypatch, tmp_path):
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
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import src.config as config_module
    import src.app as app_module

    importlib.reload(config_module)
    app_module = importlib.reload(app_module)
    monkeypatch.setattr(app_module, "_staged_root", lambda: tmp_path)
    return app_module


def test_staged_save_and_lookup_roundtrip(app_module):
    path = app_module._staged_save("abc123", "photo.png", b"data")

    staged = app_module._staged_lookup("abc123")

    assert staged is not None
    assert staged["filename"] == "photo.png"
    assert staged["path"] == path


def test_staged_lookup_returns_none_for_missing_id(app_module):
    assert app_module._staged_lookup("missing") is None