import base64
import importlib
from io import BytesIO

import pytest
from PIL import Image

from src.image_metadata import (
    license_summary,
    merge_rights,
    read_metadata,
    read_rights,
    rights_hold_missing,
    rights_missing,
    rights_status,
    validate_rights,
    write_metadata,
    write_rights,
)

SECRET = "test-mcp-secret"


def _sidecar(tmp_path, slug="women-talking", **extra):
    write_metadata(
        {
            "schemaVersion": 1,
            "slug": slug,
            "original": {"provider": "AdobeStock", "filename": f"{slug}.jpg", "license": ""},
            "standard": {"location": f"Community/{slug}.webp"},
            "focalPoint": {"x": 0.5, "y": 0.5},
            **extra,
        },
        storage_mode="local",
        image_folder=str(tmp_path),
    )


# ── validation ────────────────────────────────────────────────────────────

def test_validate_accepts_partial_and_blank_values():
    clean = validate_rights({"source": "AdobeStock", "licenseType": "", "approvedChannels": []})
    assert clean == {"source": "AdobeStock", "licenseType": "", "approvedChannels": []}


@pytest.mark.parametrize("rights, message", [
    ({"licenseType": "royalty-free"}, "licenseType"),
    ({"modelRelease": "yes"}, "modelRelease"),
    ({"licensedOn": "10/07/2026"}, "licensedOn"),
    ({"licensedOn": "2026-02-30"}, "licensedOn"),
    ({"expiration": "forever"}, "expiration"),
    ({"approvedChannels": ["web", "billboards"]}, "billboards"),
    ({"approvedChannels": "web"}, "list of strings"),
    ({"statements": [{"by": "Mike", "text": "ok"}]}, "by, on, and text"),
    ({"verification": {"status": "approved"}}, "verification.status"),
    ({"photographer": "x"}, "Unknown rights field"),
    ({"source": "Getty"}, "rights.source"),
])
def test_validate_rejects_bad_values(rights, message):
    with pytest.raises(ValueError, match=message):
        validate_rights(rights)


def test_expiration_accepts_perpetual_unknown_and_dates():
    for value in ("perpetual", "unknown", "2030-01-01"):
        assert validate_rights({"expiration": value})["expiration"] == value


def test_verified_requires_evidence_reviewer_and_date(tmp_path):
    _sidecar(tmp_path)
    with pytest.raises(ValueError, match="evidence"):
        write_rights(
            "women-talking",
            {"verification": {"status": "verified", "verifiedBy": "Mike Edwards", "verifiedOn": "2026-10-07"}},
            storage_mode="local", image_folder=str(tmp_path),
        )
    result = write_rights(
        "women-talking",
        {"verification": {
            "status": "verified", "verifiedBy": "Mike Edwards", "verifiedOn": "2026-10-07",
            "evidence": "Documents/Licenses/adobe-123.pdf",
        }},
        storage_mode="local", image_folder=str(tmp_path),
    )
    assert result["status"] == "verified"


# ── merge / read-modify-write ─────────────────────────────────────────────

def test_merge_never_erases_and_reports_conflicts():
    existing = {"contributor": "Jane", "approvedChannels": ["web"], "licenseType": "standard"}
    merged, conflicts = merge_rights(existing, {"contributor": "", "approvedChannels": [], "licenseType": "extended"})
    assert merged == existing
    assert conflicts == ["licenseType"]

    merged, conflicts = merge_rights(existing, {"licenseType": "extended"}, force=True)
    assert merged["licenseType"] == "extended" and not conflicts


def test_merge_appends_statements_once():
    statement = {"by": "Mike Edwards", "on": "2026-10-07", "text": "Licensed."}
    merged, _ = merge_rights({"statements": [statement]}, {"statements": [statement]})
    assert merged["statements"] == [statement]


def test_verification_status_cannot_be_downgraded_without_force():
    existing = {"verification": {"status": "verified"}}
    merged, conflicts = merge_rights(existing, {"verification": {"status": "unverified"}})
    assert merged["verification"]["status"] == "verified"
    assert conflicts == ["verification.status"]


def test_write_rights_is_read_modify_write(tmp_path):
    _sidecar(tmp_path)
    write_rights(
        "women-talking",
        {"statements": [{"by": "Mike Edwards", "on": "2026-10-07", "text": "Licensed via Adobe Stock."}]},
        storage_mode="local", image_folder=str(tmp_path),
    )
    write_rights(
        "women-talking", {"licenseType": "standard", "licenseReference": "LIC-1"},
        storage_mode="local", image_folder=str(tmp_path),
    )
    metadata = read_metadata("women-talking", storage_mode="local", image_folder=str(tmp_path))
    assert metadata["focalPoint"] == {"x": 0.5, "y": 0.5}
    assert metadata["standard"]["location"] == "Community/women-talking.webp"
    rights = metadata["rights"]
    assert rights["assetId"] == "women-talking"
    assert rights["source"] == "AdobeStock"
    assert rights["verification"]["status"] == "unverified"
    assert len(rights["statements"]) == 1
    assert metadata["original"]["license"] == "Adobe Stock standard license, ref LIC-1 (unverified)"


def test_write_rights_dry_run_does_not_write(tmp_path):
    _sidecar(tmp_path)
    result = write_rights("women-talking", {"licenseType": "standard"}, dry_run=True,
                          storage_mode="local", image_folder=str(tmp_path))
    assert result["rights"]["licenseType"] == "standard"
    assert "rights" not in read_metadata("women-talking", storage_mode="local", image_folder=str(tmp_path))


def test_write_rights_requires_sidecar(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_rights("missing", {"licenseType": "standard"}, storage_mode="local", image_folder=str(tmp_path))


# ── status / completeness ─────────────────────────────────────────────────

def test_status_and_missing_for_stock():
    assert rights_status(None, "AdobeStock") == "none"
    partial = {"source": "AdobeStock", "licenseType": "unknown", "verification": {"status": "unverified"}}
    assert rights_status(partial, "AdobeStock") == "incomplete"
    missing = rights_missing(partial, "AdobeStock")
    assert "licenseType" in missing and "licenseReference" in missing and "verification" in missing
    complete = {
        "providerAssetId": "123", "contributor": "Jane", "licenseType": "standard",
        "licenseReference": "LIC-1", "licensedOn": "2026-10-01", "modelRelease": "released",
        "approvedChannels": ["web"], "expiration": "perpetual", "verification": {"status": "unverified"},
    }
    assert rights_status(complete, "AdobeStock") == "unverified"
    assert rights_missing(complete, "AdobeStock") == ["verification"]


def test_hold_only_applies_to_licensed_stock():
    assert rights_hold_missing(None, "AdobeStock") == ["licenseType", "licenseReference"]
    assert rights_hold_missing({"licenseType": "standard", "licenseReference": "x"}, "ShutterStock") == []
    assert rights_hold_missing(None, "Pexels") == []


def test_license_summary_never_invents_terms():
    assert license_summary({"source": "AdobeStock"}) == "Adobe Stock: license details not yet recorded (unverified)"


# ── endpoints ─────────────────────────────────────────────────────────────

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
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "RATE_LIMIT_AUTH_REQUESTS": "50",
        "RATE_LIMIT_STREAM_REQUESTS": "50",
        "MCP_INTERNAL_SECRET": SECRET,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import src.app as app_module
    import src.config as config_module
    importlib.reload(config_module)
    app_module = importlib.reload(app_module)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_rights_endpoints_require_secret(client, tmp_path):
    _sidecar(tmp_path)
    assert client.get("/api/mcp/rights?slug=women-talking").status_code == 401
    assert client.get("/api/mcp/rights?slug=women-talking", headers={"X-MCP-Secret": "wrong"}).status_code == 401
    assert client.post("/api/mcp/rights", json={"slug": "women-talking", "rights": {}}).status_code == 401


def test_rights_get_post_round_trip(client, tmp_path):
    _sidecar(tmp_path)
    headers = {"X-MCP-Secret": SECRET}
    response = client.get("/api/mcp/rights?slug=women-talking", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["status"] == "none"

    response = client.post("/api/mcp/rights", headers=headers, json={
        "slug": "women-talking",
        "rights": {"statements": [{"by": "Mike Edwards", "on": "2026-10-07", "text": "Licensed."}]},
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["status"] == "incomplete"
    assert body["rights"]["verification"]["status"] == "unverified"
    assert "licenseReference" in body["missing"]
    assert "key=" not in response.get_data(as_text=True)

    assert client.post("/api/mcp/rights", headers=headers,
                       json={"slug": "women-talking", "rights": {"licenseType": "bogus"}}).status_code == 400
    assert client.get("/api/mcp/rights?slug=nope", headers=headers).status_code == 404


def test_rights_batch_statuses(client, tmp_path):
    _sidecar(tmp_path, slug="a")
    _sidecar(tmp_path, slug="b", rights={"source": "AdobeStock", "verification": {"status": "unverified"}})
    response = client.get("/api/mcp/rights?slugs=a,b,zzz,BAD SLUG", headers={"X-MCP-Secret": SECRET})
    assert response.status_code == 200
    assert response.get_json()["statuses"] == {"a": "none", "b": "incomplete", "zzz": "none", "BAD SLUG": "none"}
    too_many = ",".join(f"s{i}" for i in range(51))
    assert client.get(f"/api/mcp/rights?slugs={too_many}", headers={"X-MCP-Secret": SECRET}).status_code == 400


def _png_b64():
    buf = BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_catalog_from_file_holds_adobe_stock_without_license(client):
    response = client.post("/api/mcp/catalog-from-file", headers={"X-MCP-Secret": SECRET}, json={
        "image_data": _png_b64(), "filename": "women-talking.jpg", "category": "Community", "source": "AdobeStock",
    })
    assert response.status_code == 409
    assert response.get_json()["missing"] == ["licenseType", "licenseReference"]

    response = client.post("/api/mcp/catalog-from-file", headers={"X-MCP-Secret": SECRET}, json={
        "image_data": _png_b64(), "filename": "x.jpg", "category": "Community",
        "rights": {"licenseType": "royalty-free"},
    })
    assert response.status_code == 400


def test_catalog_from_file_override_passes_source_and_rights(client, monkeypatch):
    import src.image_processor as image_processor
    captured = {}

    def fake_process_image(**kwargs):
        captured.update(kwargs)
        return {"slug": "women-talking"}

    monkeypatch.setattr(image_processor, "process_image", fake_process_image)
    monkeypatch.setattr("src.ai_generator.AltTextGenerator", lambda: object())
    statement = {"by": "Mike Edwards", "on": "2026-10-07", "text": "Licensed via Adobe Stock."}
    response = client.post("/api/mcp/catalog-from-file", headers={"X-MCP-Secret": SECRET}, json={
        "image_data": _png_b64(), "filename": "women-talking.jpg", "category": "Community",
        "source": "AdobeStock", "allow_missing_rights": True,
        "rights": {"statements": [statement]},
    })
    assert response.status_code == 200
    assert captured["source"] == "AdobeStock"
    assert captured["rights"] == {"statements": [statement]}


def test_process_image_writes_rights_into_sidecar(tmp_path):
    from src.image_processor import process_image
    from test_image_processor import FakeGenerator, RecordingListClient

    buf = BytesIO()
    Image.new("RGB", (40, 30), (9, 9, 9)).save(buf, format="JPEG")
    result = process_image(
        file_bytes=buf.getvalue(),
        original_filename="women-talking.jpg",
        generator=FakeGenerator(),
        list_client=RecordingListClient(record={"id": "1"}),
        sp_client=None,
        image_folder=str(tmp_path),
        storage_mode="local",
        category="Community",
        source="AdobeStock",
        rights={"statements": [{"by": "Mike Edwards", "on": "2026-10-07", "text": "Licensed."}]},
    )
    info = read_rights(result["slug"], storage_mode="local", image_folder=str(tmp_path))
    assert info["rights"]["source"] == "AdobeStock"
    assert info["rights"]["assetId"] == result["slug"]
    assert info["status"] == "incomplete"
    assert result["original"]["license"] == "Adobe Stock: license details not yet recorded (unverified)"


def test_process_image_rejects_invalid_rights_before_upload(tmp_path):
    from src.image_processor import process_image
    from test_image_processor import FakeGenerator, RecordingListClient

    list_client = RecordingListClient(record={"id": "1"})
    with pytest.raises(ValueError):
        process_image(
            file_bytes=b"not-used", original_filename="x.jpg", generator=FakeGenerator(),
            list_client=list_client, sp_client=None, image_folder=str(tmp_path),
            storage_mode="local", rights={"licenseType": "bogus"},
        )
    assert not list_client.calls
    assert not (tmp_path / "WebP").exists()
