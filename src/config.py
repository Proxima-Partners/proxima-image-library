"""Configuration management for Asset Library."""

import os
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Configuration class for Asset Library."""

    # Airtable
    AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY", "")
    AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "")
    AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "Assets")

    # Claude AI
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # Paths
    IMAGE_FOLDER = os.getenv("IMAGE_FOLDER", "./assets")
    SUPPORTED_FORMATS = os.getenv("SUPPORTED_FORMATS", ".jpg,.jpeg,.png,.gif,.webp").split(",")

    # Test mode — uses local JSON store instead of Airtable
    TEST_MODE = os.getenv("TEST_MODE", "").lower() in ("1", "true", "yes")

    @staticmethod
    def validate():
        """Validate that all required configuration is set."""
        if Config.TEST_MODE:
            # Only Claude key is needed in test mode
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise ValueError("Missing required environment variable: ANTHROPIC_API_KEY")
            return

        required = ["AIRTABLE_API_KEY", "AIRTABLE_BASE_ID", "ANTHROPIC_API_KEY"]
        missing = [key for key in required if not os.getenv(key)]

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        base_id = os.getenv("AIRTABLE_BASE_ID", "")
        if not re.fullmatch(r"app[a-zA-Z0-9]{14}", base_id):
            raise ValueError(
                "AIRTABLE_BASE_ID must look like 'appXXXXXXXXXXXXXX' (17 chars total). "
                "Do not use a workspace id (wsp...) or include URL/query characters."
            )

        if not os.path.exists(Config.IMAGE_FOLDER):
            raise ValueError(f"Image folder not found: {Config.IMAGE_FOLDER}")
