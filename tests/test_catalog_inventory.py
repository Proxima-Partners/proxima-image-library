from io import BytesIO

from PIL import Image

from src.catalog_inventory import build_inventory
from src.image_metadata import write_metadata


def _write_original(root, location, width):
    path = root / "High-Res" / location
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, 500), "navy")
    buf = BytesIO()
    image.save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())


def test_inventory_is_read_only_and_groups_resolution_and_metadata_gaps(tmp_path):
    records = []
    for index, width in enumerate((3000, 1600, 1200, 2000), 1):
        location = f"Internal/image-{index}.jpg"
        _write_original(tmp_path, location, width)
        records.append({
            "id": str(index),
            "fields": {
                "Slug": f"image-{index}",
                "Filename": f"image-{index}.webp",
                "High-Res Location": location,
                "Source": "Internal",
            },
        })

    report = build_inventory(records, storage_mode="local", image_folder=str(tmp_path))

    assert report["dryRun"] is True
    assert report["summary"]["heroEligible"] == 1
    assert report["summary"]["storedOriginalOnly1600"] == 1
    assert report["summary"]["below1600"] == 1
    assert report["summary"]["standardOnly1601To2559"] == 1
    assert report["summary"]["metadataGaps"] == 4
    assert not (tmp_path / "Hero").exists()


def test_inventory_reports_rights_status_and_png_gaps(tmp_path):
    records = []
    for slug, source, rights in (
        ("stock-none", "AdobeStock", None),
        ("stock-partial", "AdobeStock", {"source": "AdobeStock", "verification": {"status": "unverified"}}),
        ("internal-ok", "Internal", {
            "licenseType": "internal", "modelRelease": "not-required",
            "approvedChannels": ["web"], "verification": {"status": "unverified"},
        }),
        ("internal-verified", "Internal", {"verification": {
            "status": "verified", "verifiedBy": "Mike Edwards", "verifiedOn": "2026-10-07", "evidence": "x.pdf",
        }}),
    ):
        _write_original(tmp_path, f"{source}/{slug}.jpg", 1600)
        metadata = {
            "slug": slug,
            "original": {"provider": source},
            "standard": {"location": f"Community/{slug}.webp"},
            "focalPoint": {"x": 0.5, "y": 0.5},
        }
        if rights:
            metadata["rights"] = rights
        write_metadata(metadata, storage_mode="local", image_folder=str(tmp_path))
        records.append({"id": slug, "fields": {
            "Slug": slug, "Source": source, "High-Res Location": f"{source}/{slug}.jpg",
        }})

    report = build_inventory(records, storage_mode="local", image_folder=str(tmp_path))

    assert report["rightsStatus"] == {"verified": 1, "unverified": 1, "incomplete": 1, "none": 1}
    gaps = {item["slug"]: item for item in report["metadataGaps"]}
    assert set(gaps) == {"stock-none", "stock-partial"}
    assert "licenseReference" in gaps["stock-partial"]["rightsMissing"]
    assert report["summary"]["pngMissing"] == 4
