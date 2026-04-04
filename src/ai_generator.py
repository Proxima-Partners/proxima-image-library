"""AI-powered alt text generation using Claude."""

import base64
from pathlib import Path
from typing import Optional, Union
from anthropic import Anthropic
from src.config import Config

# Maps file extensions to MIME types for the Claude API
_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class AltTextGenerator:
    """Generate alt text for images using Claude's vision capabilities.

    Accepts either a local file path (str) or raw image bytes.
    When passing bytes, also pass the filename so the media type can be derived.
    """

    def __init__(self):
        self.client = Anthropic()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _encode(self, source: Union[str, bytes], filename: str = "") -> tuple[str, str]:
        """Return (base64_data, media_type) from a path or bytes."""
        if isinstance(source, bytes):
            ext = Path(filename).suffix.lower() if filename else ".jpg"
            media_type = _MEDIA_TYPES.get(ext, "image/jpeg")
            return base64.standard_b64encode(source).decode("utf-8"), media_type

        # Local file path
        path = Path(source)
        media_type = _MEDIA_TYPES.get(path.suffix.lower(), "image/jpeg")
        with open(path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8"), media_type

    def _vision_message(self, source: Union[str, bytes], filename: str, prompt: str) -> str:
        """Send a vision request to Claude and return the response text."""
        image_data, media_type = self._encode(source, filename)
        message = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return message.content[0].text.strip()

    # ------------------------------------------------------------------
    # Legacy helpers (kept for backwards compatibility)
    # ------------------------------------------------------------------

    def encode_image(self, image_path: str) -> str:
        data, _ = self._encode(image_path)
        return data

    def get_image_media_type(self, image_path: str) -> str:
        return _MEDIA_TYPES.get(Path(image_path).suffix.lower(), "image/jpeg")

    def generate_alt_text(
        self,
        source: Union[str, bytes],
        context: Optional[str] = None,
        max_length: int = 125,
        filename: str = "",
    ) -> Optional[str]:
        """Generate alt text for an image using Claude.

        Args:
            source:    Local file path (str) OR raw image bytes
            context:   Optional context about the image
            max_length: Max characters for alt text (default 125)
            filename:  Original filename — required when source is bytes
                       so the media type can be derived from the extension
        """
        try:
            if isinstance(source, str):
                if not Path(source).exists():
                    print(f"Image file not found: {source}")
                    return None
                filename = filename or source

            prompt = (
                f"Analyze this image and generate a concise, descriptive alt text for web accessibility.\n"
                f"The alt text should:\n"
                f"- Be descriptive but concise (max {max_length} characters)\n"
                f"- Describe what's in the image without being overly detailed\n"
                f"- Be suitable for screen readers\n"
                f"- Not start with 'Image of' or 'Picture of'\n"
            )
            if context:
                prompt += f"\nContext: {context}\n"
            prompt += "\nGenerate ONLY the alt text, nothing else."

            return self._vision_message(source, filename, prompt)

        except Exception as e:
            print(f"Error generating alt text for {filename or source}: {e}")
            return None

    def generate_tags(
        self,
        source: Union[str, bytes],
        context: Optional[str] = None,
        filename: str = "",
    ) -> Optional[str]:
        """Generate comma-separated tags for an image using Claude.

        Args:
            source:   Local file path (str) OR raw image bytes
            context:  Optional context about the image
            filename: Original filename — required when source is bytes
        """
        try:
            if isinstance(source, str):
                if not Path(source).exists():
                    return None
                filename = filename or source

            # Load current vocabulary from TagLibrary
            from src.tag_library import TagLibrary
            allowed = ", ".join(TagLibrary.instance().get_flat())

            prompt = f"""Analyze this image and select 2-5 tags from the following approved list.

Approved tags:
{allowed}

Rules:
- Prefer tags from the approved list above
- If an important aspect of the image has no good match in the list, you may suggest \
up to 2 new tags by prefixing them with '?' (e.g. ?rooftop-garden)
- Suggested tags must be lowercase and hyphenated (no spaces or special characters)
- Return ONLY a comma-separated list, nothing else
- No punctuation other than commas and the '?' suggestion prefix"""

            if context:
                prompt += f"\nContext: {context}"

            return self._vision_message(source, filename, prompt)

        except Exception as e:
            print(f"Error generating tags for {filename or source}: {e}")
            return None

    # Keep old signature working for any callers that pass image_path positionally
    # (batch_generate_alt_text etc.)
    def _generate_tags_legacy(
        self,
        image_path: str,
        context: Optional[str] = None,
    ) -> Optional[str]:
        """Legacy wrapper — remove once all callers updated."""
        try:
            if not Path(image_path).exists():
                return None

            return self.generate_tags(image_path, context)

        except Exception as e:
            print(f"Error generating tags for {image_path}: {e}")
            return None

    def batch_generate_alt_text(
        self,
        image_paths: list,
        context: Optional[str] = None,
    ) -> dict:
        """Generate alt text for multiple images.

        Args:
            image_paths: List of image file paths
            context: Optional context about the images

        Returns:
            Dictionary mapping image paths to generated alt text
        """
        results = {}
        for i, image_path in enumerate(image_paths, 1):
            print(f"Processing image {i}/{len(image_paths)}: {Path(image_path).name}")
            alt_text = self.generate_alt_text(image_path, context)
            results[image_path] = alt_text
        return results
