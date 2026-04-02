"""AI-powered alt text generation using Claude."""

import base64
from pathlib import Path
from typing import Optional
from anthropic import Anthropic
from src.config import Config


class AltTextGenerator:
    """Generate alt text for images using Claude's vision capabilities."""

    def __init__(self):
        """Initialize the alt text generator."""
        self.client = Anthropic()
        self.api_key = Config.ANTHROPIC_API_KEY

    def encode_image(self, image_path: str) -> str:
        """Encode image to base64 for Claude API.

        Args:
            image_path: Path to the image file

        Returns:
            Base64-encoded image string
        """
        with open(image_path, "rb") as image_file:
            return base64.standard_b64encode(image_file.read()).decode("utf-8")

    def get_image_media_type(self, image_path: str) -> str:
        """Determine the media type of the image.

        Args:
            image_path: Path to the image file

        Returns:
            Media type string (e.g., 'image/jpeg')
        """
        suffix = Path(image_path).suffix.lower()
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return media_types.get(suffix, "image/jpeg")

    def generate_alt_text(
        self,
        image_path: str,
        context: Optional[str] = None,
        max_length: int = 125,
    ) -> Optional[str]:
        """Generate alt text for an image using Claude.

        Args:
            image_path: Path to the image file
            context: Optional context about the image or project
            max_length: Maximum length of alt text (default: 125 chars)

        Returns:
            Generated alt text string or None if generation failed
        """
        try:
            # Check if file exists
            if not Path(image_path).exists():
                print(f"Image file not found: {image_path}")
                return None

            # Encode image
            image_data = self.encode_image(image_path)
            media_type = self.get_image_media_type(image_path)

            # Build prompt
            prompt = f"""Analyze this image and generate a concise, descriptive alt text for web accessibility. 
The alt text should:
- Be descriptive but concise (max {max_length} characters)
- Describe what's in the image without being overly detailed
- Be suitable for screen readers
- Not start with 'Image of' or 'Picture of'

"""
            if context:
                prompt += f"Context: {context}\n\n"

            prompt += "Generate ONLY the alt text, nothing else."

            # Call Claude API
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=150,
                messages=[
                    {
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
                    }
                ],
            )

            alt_text = message.content[0].text.strip()
            return alt_text

        except Exception as e:
            print(f"Error generating alt text for {image_path}: {e}")
            return None

    def generate_tags(
        self,
        image_path: str,
        context: Optional[str] = None,
    ) -> Optional[str]:
        """Generate comma-separated tags for an image using Claude.

        Args:
            image_path: Path to the image file
            context: Optional context about the image or project

        Returns:
            Comma-separated tags string or None if generation failed
        """
        try:
            if not Path(image_path).exists():
                return None

            image_data = self.encode_image(image_path)
            media_type = self.get_image_media_type(image_path)

            prompt = """Analyze this image and select 2-5 tags from the following list that best describe what the image shows.

Allowed tags:
people, headshot, group, individual, staff, volunteer, family, youth, children, elderly, unhoused, neighbor, community
city, san-francisco, bay-area, golden-gate, landscape, architecture, street, cafe, office, church, indoor, outdoor, mission-district
park, beach, mountains, waterfront, urban, suburban, rural, forest, plaza, rooftop, bridge, neighborhood
hope, connection, service, prayer, celebration, hardship, joy, loneliness, generosity
icon, logo, illustration, graphic, vector, document, map, badge, partner
portrait, thumbnail, banner, background, photo

Rules:
- Only use tags from the list above — do not invent new ones
- Return ONLY a comma-separated list, nothing else
- No punctuation other than commas"""

            if context:
                prompt += f"\nContext: {context}"

            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=80,
                messages=[
                    {
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
                    }
                ],
            )

            return message.content[0].text.strip()

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
