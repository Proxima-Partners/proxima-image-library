"""Configuration management for Asset Library."""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Configuration class for Asset Library."""

    # Claude AI
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # Paths
    IMAGE_FOLDER = os.getenv("IMAGE_FOLDER", "./assets")
    SUPPORTED_FORMATS = os.getenv("SUPPORTED_FORMATS", ".jpg,.jpeg,.png,.gif,.webp").split(",")
    TAG_LIBRARY_PATH = os.getenv(
        "TAG_LIBRARY_PATH",
        "~/Applications/Image-Library/Config/tag_library.json",
    )

    # Test mode — uses local JSON store instead of Airtable
    TEST_MODE = os.getenv("TEST_MODE", "").lower() in ("1", "true", "yes")

    # Storage mode — "local" uses IMAGE_FOLDER; "sharepoint" uses Microsoft Graph API
    STORAGE_MODE = os.getenv("STORAGE_MODE", "local").lower()

    # Flask session
    FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-prod")

    # MSAL user authentication
    MSAL_CLIENT_ID = os.getenv("MSAL_CLIENT_ID", "")
    MSAL_CLIENT_SECRET = os.getenv("MSAL_CLIENT_SECRET", "")
    MSAL_TENANT_ID = os.getenv("MSAL_TENANT_ID", os.getenv("SHAREPOINT_TENANT_ID", ""))
    MSAL_REDIRECT_URI = os.getenv("MSAL_REDIRECT_URI", "http://localhost:5000/auth/callback")
    MSAL_AUTHORITY = f"https://login.microsoftonline.com/{os.getenv('MSAL_TENANT_ID', os.getenv('SHAREPOINT_TENANT_ID', ''))}"
    MSAL_SCOPES = ["User.Read"]

    # CORS — comma-separated list of allowed origins for /api/* routes
    # e.g. https://yoursite.webflow.io,https://yourdomain.com
    CORS_ORIGINS = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5000").split(",")
        if o.strip()
    ]

    # SharePoint / Microsoft Graph API
    SHAREPOINT_TENANT_ID = os.getenv("SHAREPOINT_TENANT_ID", "")
    SHAREPOINT_CLIENT_ID = os.getenv("SHAREPOINT_CLIENT_ID", "")
    SHAREPOINT_CLIENT_SECRET = os.getenv("SHAREPOINT_CLIENT_SECRET", "")
    SHAREPOINT_DRIVE_ID = os.getenv("SHAREPOINT_DRIVE_ID", "")
    SHAREPOINT_SITE_ID = os.getenv("SHAREPOINT_SITE_ID", "")
    SHAREPOINT_LIST_NAME = os.getenv("SHAREPOINT_LIST_NAME", "Assets")
    SHAREPOINT_IMAGE_FOLDER = os.getenv("SHAREPOINT_IMAGE_FOLDER", "Images")

    @staticmethod
    def validate():
        """Validate that all required configuration is set."""
        if Config.TEST_MODE:
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise ValueError("Missing required environment variable: ANTHROPIC_API_KEY")
            return

        required = [
            "ANTHROPIC_API_KEY",
            "SHAREPOINT_TENANT_ID",
            "SHAREPOINT_CLIENT_ID",
            "SHAREPOINT_CLIENT_SECRET",
            "SHAREPOINT_SITE_ID",
            "SHAREPOINT_DRIVE_ID",
        ]
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
