import importlib
from io import BytesIO

import pytest
from PIL import Image

from src.image_metadata import read_metadata, write_metadata
from src.png_backfill import backfill_png, needs_png


def _image_bytes(width, height, image_format="JPEG"):
    buf = BytesIO()
    Image.new("RGB", (width, height), (30, 90, 150)).save(buf, format=image_format)
    return buf.getvalue()


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _seed(tmp_path, *, slug="wide", width=2600, with_original=True, with_hero=True):
    location = f"Banners/{slug}.webp"
    original_location = f"Internal/{slug}-original.jpg"
    if with_original:
        _write(tmp_path / "High-Res" / original_location, _image_bytes(width, width // 2))
    _write(tmp_path / "WebP" / location, _image_bytes(1600, 800, "WEBP"))
    if with_hero:
        _write(tmp_path / "Hero" / location, _image_bytes(2560, 1280, "WEBP"))
    metadata = {
        "schemaVersion": 1,
        "slug": slug,
        "original": {"location": original_location, "attribution": "Credit"},
        "standard": {"location": location, "width": 1600, "height": 800},
        "hero": {"location": location, "width": 2560, "height": 1280} if with_hero else None,
        "focalPoint": {"x": 0.3, "y": 0.6},
        "rights": {"source": "Internal", "licenseType": "internal", "verification": {"status": "unverified"}},
    }
    write_metadata(metadata, storage_mode="local", image_folder=str(tmp_path))
    record = {"id": "1", "fields": {"Slug": slug, "Location": location, "High-Res Location": original_location}}
    return record, metadata


def _run(record, tmp_path, **kwargs):
    return backfill_png(record, storage_mode="local", image_folder=str(tmp_path), **kwargs)


def test_creates_standard_and_hero_png_and_preserves_other_keys(tmp_path):
    record, before = _seed(tmp_path)
    result = _run(record, tmp_path)
    assert result["status"] == "done"
    assert (result["standardPng"], result["heroPng"], result["pngSource"]) == ("created", "created", "original")
    with Image.open(tmp_path / "PNG/Banners/wide.png") as png:
        assert (png.format, png.size) == ("PNG", (1600, 800))
    with Image.open(tmp_path / "Hero-PNG/Banners/wide.png") as png:
        assert png.size == (2560, 1280)

    after = read_metadata("wide", storage_mode="local", image_folder=str(tmp_path))
    for key in ("rights", "original", "focalPoint"):
        assert after[key] == before[key]
    assert after["standard"]["png"]["location"] == "Banners/wide.png"
    assert after["hero"]["png"]["location"] == "Banners/wide.png"
    assert not needs_png(after)


def test_second_run_is_a_no_op(tmp_path):
    record, _ = _seed(tmp_path)
    _run(record, tmp_path)
    mtime = (tmp_path / "PNG/Banners/wide.png").stat().st_mtime_ns
    assert _run(record, tmp_path)["status"] == "exists"
    assert (tmp_path / "PNG/Banners/wide.png").stat().st_mtime_ns == mtime


def test_no_hero_means_no_hero_png(tmp_path):
    record, _ = _seed(tmp_path, slug="medium", width=1800, with_hero=False)
    result = _run(record, tmp_path)
    assert (result["standardPng"], result["heroPng"]) == ("created", "n/a")
    assert not (tmp_path / "Hero-PNG").exists()


def test_falls_back_to_webp_when_original_missing(tmp_path):
    record, _ = _seed(tmp_path, with_original=False)
    result = _run(record, tmp_path)
    assert result["pngSource"] == "webp"
    with Image.open(tmp_path / "PNG/Banners/wide.png") as png:
        assert png.size == (1600, 800)


def test_record_without_sidecar_is_skipped(tmp_path):
    record = {"id": "2", "fields": {"Slug": "ghost", "Location": "Banners/ghost.webp"}}
    result = _run(record, tmp_path)
    assert result["status"] == "skipped"
    assert "no-sidecar" in result["reason"]


def test_dry_run_writes_nothing(tmp_path):
    record, before = _seed(tmp_path)
    result = _run(record, tmp_path, dry_run=True)
    assert (result["status"], result["standardPng"], result["heroPng"]) == ("planned", "planned", "planned")
    assert not (tmp_path / "PNG").exists()
    assert read_metadata("wide", storage_mode="local", image_folder=str(tmp_path)) == before


# ── download route + variations ───────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, tmp_path):
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
        "IMAGE_FOLDER": str(tmp_path),
        "MCP_INTERNAL_SECRET": "test-mcp-secret",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import src.app as app_module
    import src.config as config_module
    importlib.reload(config_module)
    app_module = importlib.reload(app_module)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def _login(client):
    with client.session_transaction() as sess:
        sess["user"] = {"preferred_username": "user@example.com"}
        sess["_csrf_token"] = "t"


def test_download_requires_login(client, tmp_path):
    _seed(tmp_path)
    response = client.get("/image/download?area=WebP&path=Banners/wide.webp&download=1")
    assert response.status_code in (302, 401)


def test_download_stored_png_as_attachment(client, tmp_path):
    record, _ = _seed(tmp_path)
    _run(record, tmp_path)
    _login(client)
    response = client.get("/image/download?area=Hero-PNG&path=Banners/wide.png&download=1")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Content-Disposition"] == 'attachment; filename="wide-hero.png"'


def test_download_webp_attachment_and_png_fallback_conversion(client, tmp_path):
    _seed(tmp_path)
    _login(client)
    webp = client.get("/image/download?area=WebP&path=Banners/wide.webp&download=1")
    assert webp.mimetype == "image/webp"
    assert 'filename="wide-standard.webp"' in webp.headers["Content-Disposition"]

    png = client.get("/image/download?area=WebP&path=Banners/wide.webp&format=png&download=1")
    assert png.status_code == 200 and png.mimetype == "image/png"
    with Image.open(BytesIO(png.data)) as img:
        assert (img.format, img.size) == ("PNG", (1600, 800))


@pytest.mark.parametrize("query", [
    "area=High-Res&path=Internal/wide-original.jpg&format=png",
    "area=WebP&path=Banners/wide.webp&format=gif",
    "area=Secrets&path=x.png",
    "area=PNG&path=../etc/passwd",
])
def test_download_rejects_bad_requests(client, tmp_path, query):
    _seed(tmp_path)
    _login(client)
    assert client.get(f"/image/download?{query}").status_code == 400


def test_variations_offer_webp_and_png_downloads(client, tmp_path):
    record, _ = _seed(tmp_path)
    _login(client)
    data = client.get("/api/image/variations?path=Banners/wide.webp").get_json()
    by_key = {v["key"]: v for v in data["variations"]}
    # Not backfilled yet: PNG link converts on the fly.
    assert [d["label"] for d in by_key["standard"]["downloads"]] == ["WEBP", "PNG"]
    assert "format=png" in by_key["standard"]["downloads"][1]["url"]
    assert data["rights"] == {"licenseType": "internal", "verificationStatus": "unverified", "expiration": "unknown"}

    _run(record, tmp_path)
    data = client.get("/api/image/variations?path=Banners/wide.webp").get_json()
    by_key = {v["key"]: v for v in data["variations"]}
    assert by_key["hero"]["downloads"][1]["url"].startswith("/image/download?area=Hero-PNG&path=Banners/wide.png")
    assert [d["label"] for d in by_key["original"]["downloads"]] == ["JPG"]
