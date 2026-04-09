from src.image_processor import process_image


class FakeGenerator:
    def generate_category(self, _webp_bytes, _categories, filename=""):
        return "Headshots"

    def generate_alt_text(self, _webp_bytes, context=None, filename=""):
        return "Person smiling outdoors"

    def generate_tags(self, _webp_bytes, context=None, filename=""):
        return "portrait, outdoor"


class RecordingListClient:
    def __init__(self, record=None):
        self.record = record
        self.calls = []

    def record_exists(self, _filename):
        return False

    def create_record(self, **kwargs):
        self.calls.append(kwargs)
        return self.record


class RecordingSpClient:
    def __init__(self):
        self.uploads = []

    def upload_file(self, folder_path, filename, content_bytes):
        self.uploads.append((folder_path, filename, len(content_bytes)))
        return {"name": filename}


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc``\xf8\xcf\x00\x00\x02\x01\x01\x00"
    b"\x18\xdd\x8d\xb1"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_process_image_raises_when_record_creation_fails(tmp_path):
    generator = FakeGenerator()
    list_client = RecordingListClient(record=None)
    sp_client = RecordingSpClient()

    try:
        process_image(
            file_bytes=PNG_BYTES,
            original_filename="headshot.png",
            generator=generator,
            list_client=list_client,
            sp_client=sp_client,
            image_folder=str(tmp_path),
            storage_mode="sharepoint",
            source="Internal",
        )
        assert False, "Expected metadata record creation to fail"
    except RuntimeError as exc:
        assert str(exc) == "Metadata record creation failed"


def test_process_image_returns_result_when_record_creation_succeeds(tmp_path):
    generator = FakeGenerator()
    list_client = RecordingListClient(record={"id": "sp_123"})
    sp_client = RecordingSpClient()

    result = process_image(
        file_bytes=PNG_BYTES,
        original_filename="headshot.png",
        generator=generator,
        list_client=list_client,
        sp_client=sp_client,
        image_folder=str(tmp_path),
        storage_mode="sharepoint",
        source="Internal",
    )

    assert result["status"] == "pending-review"
    assert result["filename"].endswith(".webp")
    assert len(sp_client.uploads) == 2
    assert list_client.calls[0]["location"].startswith("Headshots/")