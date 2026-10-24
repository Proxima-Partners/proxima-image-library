import json

import pytest

from src import image_metadata
from src.image_metadata import read_metadata, update_focal_point, write_metadata


class RecordingSharePointClient:
    def __init__(self, metadata):
        self.metadata = metadata
        self.list_calls = 0
        self.read_calls = 0
        self.uploads = []

    def list_folder(self, _folder):
        self.list_calls += 1
        return [{"name": f"{self.metadata['slug']}.json"}]

    def get_file_bytes(self, _path):
        self.read_calls += 1
        return json.dumps(self.metadata).encode()

    def upload_file(self, folder, filename, content):
        self.uploads.append((folder, filename))
        self.metadata = json.loads(content)
        return {"name": filename}


@pytest.fixture(autouse=True)
def clear_sidecar_caches():
    with image_metadata._SIDECAR_CACHE_LOCK:
        image_metadata._SIDECAR_CACHE.clear()
        image_metadata._SIDECAR_DOCUMENT_CACHE.clear()
    yield
    with image_metadata._SIDECAR_CACHE_LOCK:
        image_metadata._SIDECAR_CACHE.clear()
        image_metadata._SIDECAR_DOCUMENT_CACHE.clear()


def test_editor_can_revise_normalized_focal_point(tmp_path):
    metadata = {
        "slug": "sample-image",
        "focalPoint": {"x": 0.5, "y": 0.5},
        "qualityTier": "hero-ready",
    }
    write_metadata(metadata, storage_mode="local", image_folder=str(tmp_path))

    updated = update_focal_point(
        "sample-image",
        0.25,
        0.8,
        storage_mode="local",
        image_folder=str(tmp_path),
    )

    assert updated["focalPoint"] == {"x": 0.25, "y": 0.8}
    assert read_metadata(
        "sample-image", storage_mode="local", image_folder=str(tmp_path)
    )["qualityTier"] == "hero-ready"


def test_focal_point_rejects_out_of_range_values(tmp_path):
    write_metadata(
        {"slug": "sample-image", "focalPoint": {"x": 0.5, "y": 0.5}},
        storage_mode="local",
        image_folder=str(tmp_path),
    )
    with pytest.raises(ValueError):
        update_focal_point(
            "sample-image", 1.1, 0.5,
            storage_mode="local", image_folder=str(tmp_path),
        )


def test_sharepoint_metadata_document_is_cached_and_returns_private_copies(monkeypatch):
    monkeypatch.setattr(image_metadata.Config, "SHAREPOINT_IMAGE_FOLDER", "Images")
    client = RecordingSharePointClient({"slug": "sample-image", "qualityTier": "hero-ready"})

    first = read_metadata("sample-image", storage_mode="sharepoint", sp_client=client)
    first["qualityTier"] = "changed-by-caller"
    second = read_metadata("sample-image", storage_mode="sharepoint", sp_client=client)

    assert second["qualityTier"] == "hero-ready"
    assert client.list_calls == 1
    assert client.read_calls == 1


def test_sharepoint_metadata_write_refreshes_document_cache(monkeypatch):
    monkeypatch.setattr(image_metadata.Config, "SHAREPOINT_IMAGE_FOLDER", "Images")
    client = RecordingSharePointClient({"slug": "sample-image", "qualityTier": "standard-only"})
    assert read_metadata("sample-image", storage_mode="sharepoint", sp_client=client)["qualityTier"] == "standard-only"

    write_metadata(
        {"slug": "sample-image", "qualityTier": "hero-ready"},
        storage_mode="sharepoint",
        image_folder="unused",
        sp_client=client,
    )

    assert read_metadata("sample-image", storage_mode="sharepoint", sp_client=client)["qualityTier"] == "hero-ready"
    assert client.read_calls == 1
    assert client.uploads == [("Images/Metadata", "sample-image.json")]
