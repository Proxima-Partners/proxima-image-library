from pathlib import Path


def test_badge_module_is_packaged_with_its_template():
    # Runs inside the actual target image as well as the checkout; a browser
    # unit test alone cannot detect a deny-by-default Docker context omission.
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "index.html").read_text()
    module = (root / "static" / "review-badge.js").read_text()
    assert "filename='review-badge.js'" in template
    assert "createReviewBadgePoller" in template and "createReviewBadgePoller" in module
