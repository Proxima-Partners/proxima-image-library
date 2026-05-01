import importlib

import pytest


class _FakeTagLibrary:
    def __init__(self):
        self.promoted = []
        self.cache_invalidated = False

    def promote_suggestion(self, tag, category):
        self.promoted.append((tag, category))

    def invalidate_cache(self):
        self.cache_invalidated = True


class _FakeClient:
    def __init__(self):
        self.records = [
            {"id": "1", "fields": {"Tags": "?New-Tag, existing"}},
            {"id": "2", "fields": {"Tags": "keep, ?new-tag"}},
            {"id": "3", "fields": {"Tags": "?different"}},
            {"id": "4", "fields": {"Tags": "new-tag"}},
        ]
        self.patches = []

    def get_all_records(self):
        return self.records

    def bulk_patch_fields(self, patches):
        self.patches.extend(patches)


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
    app_module.app.config.update(TESTING=True)
    return app_module


def test_single_promote_cleans_prefixed_tags(monkeypatch, app_module):
    fake_client = _FakeClient()
    fake_lib = _FakeTagLibrary()

    import src.tag_library as tag_library_module

    monkeypatch.setattr(app_module, "get_client", lambda: fake_client)
    monkeypatch.setattr(tag_library_module.TagLibrary, "instance", classmethod(lambda cls: fake_lib))

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"preferred_username": "admin@example.com"}

    response = client.post(
        "/api/tag-library/promote",
        json={"tag": "?new-tag", "category": "Custom"},
        headers={"Origin": "http://localhost", "Referer": "http://localhost/tag-manager"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert fake_lib.promoted == [("?new-tag", "Custom")]
    assert fake_lib.cache_invalidated is True
    assert fake_client.patches == [
        ("1", {"Tags": "new-tag, existing"}),
        ("2", {"Tags": "keep, new-tag"}),
    ]
    assert app_module._records_cache is None


def test_bulk_promote_cleans_prefixed_tags(monkeypatch, app_module):
    fake_client = _FakeClient()
    fake_lib = _FakeTagLibrary()

    import src.tag_library as tag_library_module

    monkeypatch.setattr(app_module, "get_client", lambda: fake_client)
    monkeypatch.setattr(tag_library_module.TagLibrary, "instance", classmethod(lambda cls: fake_lib))

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"preferred_username": "admin@example.com"}

    response = client.post(
        "/api/tag-library/promote-bulk",
        json={
            "tags": [
                {"tag": "?new-tag", "category": "Custom"},
                {"tag": "?different", "category": "Custom"},
            ]
        },
        headers={"Origin": "http://localhost", "Referer": "http://localhost/tag-manager"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "promoted": 2}
    assert fake_lib.promoted == [
        ("?new-tag", "Custom"),
        ("?different", "Custom"),
    ]
    assert fake_lib.cache_invalidated is True
    assert fake_client.patches == [
        ("1", {"Tags": "new-tag, existing"}),
        ("2", {"Tags": "keep, new-tag"}),
        ("3", {"Tags": "different"}),
    ]
    assert app_module._records_cache is None
