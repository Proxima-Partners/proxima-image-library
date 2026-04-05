"""Tests for rename_assets.py — slugify and build_plan logic."""

import pytest
from pathlib import Path
from src.rename_assets import slugify, build_plan


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_lowercase(self):
        # slugify does not split camelCase — it just lowercases
        assert slugify("HelloWorld") == "helloworld"

    def test_spaces_become_dashes(self):
        assert slugify("ways to give") == "ways-to-give"

    def test_special_chars_stripped(self):
        assert slugify("cell-phone_white") == "cell-phone-white"

    def test_consecutive_separators_collapsed(self):
        assert slugify("foo___bar---baz") == "foo-bar-baz"

    def test_leading_trailing_separators_stripped(self):
        assert slugify("--image--") == "image"

    def test_empty_string_fallback(self):
        assert slugify("") == "image"

    def test_only_special_chars_fallback(self):
        assert slugify("!!!") == "image"

    def test_numbers_preserved(self):
        assert slugify("photo2025") == "photo2025"

    def test_mixed_case_with_numbers(self):
        assert slugify("Square-Katie-Web4") == "square-katie-web4"


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------

class TestBuildPlan:
    def _make_images(self, names, base="/tmp/assets"):
        """Helper: build (full_path, relative_path) tuples from filenames."""
        return [(f"{base}/{n}", n) for n in names]

    def test_basic_rename(self, tmp_path):
        src = tmp_path / "photo.jpg"
        src.touch()
        images = [(str(src), "photo.jpg")]
        plan = build_plan(images, prefix="pfx", start_index=1)
        assert len(plan) == 1
        old, new = plan[0]
        assert new.name == "pfx-photo.jpg"

    def test_extension_lowercased(self, tmp_path):
        src = tmp_path / "Securities.PNG"
        src.touch()
        images = [(str(src), "Securities.PNG")]
        plan = build_plan(images, prefix="pfx", start_index=1)
        _, new = plan[0]
        assert new.suffix == ".png"

    def test_sorted_alphabetically(self, tmp_path):
        files = ["zebra.png", "apple.jpg", "mango.webp"]
        paths = []
        for f in files:
            p = tmp_path / f
            p.touch()
            paths.append((str(p), f))
        plan = build_plan(paths, prefix="pfx", start_index=1)
        names = [new.name for _, new in plan]
        assert names[0].startswith("pfx-apple")
        assert names[1].startswith("pfx-mango")
        assert names[2].startswith("pfx-zebra")

    def test_start_index_respected(self, tmp_path):
        """start_index is no longer used in the filename; test that build_plan still runs."""
        src = tmp_path / "img.jpg"
        src.touch()
        plan = build_plan([(str(src), "img.jpg")], prefix="pfx", start_index=10)
        _, new = plan[0]
        assert new.name == "pfx-img.jpg"

    def test_already_named_files_are_skipped(self, tmp_path):
        """A file already matching the target naming convention is skipped."""
        name = "pfx-img.jpg"
        src = tmp_path / name
        src.touch()
        plan = build_plan([(str(src), name)], prefix="pfx", start_index=1)
        assert len(plan) == 0

    def test_empty_input(self):
        assert build_plan([], prefix="pfx", start_index=1) == []


# ---------------------------------------------------------------------------
# ImageScanner
# ---------------------------------------------------------------------------

class TestImageScanner:
    def test_finds_supported_images(self, tmp_path):
        from src.image_scanner import ImageScanner
        (tmp_path / "a.jpg").touch()
        (tmp_path / "b.PNG").touch()
        (tmp_path / "c.txt").touch()
        scanner = ImageScanner(folder=str(tmp_path), supported_formats=[".jpg", ".png"])
        results = scanner.get_all_images()
        names = {Path(fp).name for fp, _ in results}
        assert "a.jpg" in names
        assert "b.PNG" in names
        assert "c.txt" not in names

    def test_recursive_scan(self, tmp_path):
        from src.image_scanner import ImageScanner
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.webp").touch()
        scanner = ImageScanner(folder=str(tmp_path), supported_formats=[".webp"])
        results = scanner.get_all_images()
        assert len(results) == 1
        assert Path(results[0][0]).name == "deep.webp"

    def test_missing_folder_returns_empty(self):
        from src.image_scanner import ImageScanner
        scanner = ImageScanner(folder="/nonexistent/path/xyz")
        assert scanner.get_all_images() == []

    def test_get_new_images_excludes_processed(self, tmp_path):
        from src.image_scanner import ImageScanner
        (tmp_path / "old.jpg").touch()
        (tmp_path / "new.jpg").touch()
        scanner = ImageScanner(folder=str(tmp_path), supported_formats=[".jpg"])
        results = scanner.get_new_images(processed_files=["old.jpg"])
        names = [Path(fp).name for fp, _ in results]
        assert "new.jpg" in names
        assert "old.jpg" not in names
