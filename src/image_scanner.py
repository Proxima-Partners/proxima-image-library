"""Image scanning and file handling utilities."""

from pathlib import Path
from typing import List, Tuple
from src.config import Config


class ImageScanner:
    """Scan and process image files from a directory."""

    def __init__(self, folder: str = None, supported_formats: List[str] = None):
        """Initialize the image scanner.

        Args:
            folder: Path to the image folder (uses config if not provided)
            supported_formats: List of supported file extensions
        """
        self.folder = Path(folder or Config.IMAGE_FOLDER)
        self.supported_formats = supported_formats or Config.SUPPORTED_FORMATS

    def get_all_images(self) -> List[Tuple[str, str]]:
        """Get all images in the folder and subfolders.

        Returns:
            List of tuples (full_path, relative_path) for each image
        """
        images = []

        if not self.folder.exists():
            print(f"Folder not found: {self.folder}")
            return images

        # Normalize formats to lowercase with dots
        formats = [fmt if fmt.startswith(".") else f".{fmt}" for fmt in self.supported_formats]
        formats = [fmt.lower() for fmt in formats]

        for image_file in self.folder.rglob("*"):
            if image_file.is_file() and image_file.suffix.lower() in formats:
                full_path = str(image_file.resolve())
                relative_path = str(image_file.relative_to(self.folder))
                images.append((full_path, relative_path))

        return images

    def get_new_images(self, processed_files: List[str]) -> List[Tuple[str, str]]:
        """Get images that haven't been processed yet.

        Args:
            processed_files: List of filenames that have already been processed

        Returns:
            List of tuples (full_path, relative_path) for unprocessed images
        """
        all_images = self.get_all_images()
        processed_basenames = {Path(f).name for f in processed_files}

        new_images = [
            (full_path, relative_path)
            for full_path, relative_path in all_images
            if Path(relative_path).name not in processed_basenames
        ]

        return new_images

    def get_image_count(self) -> int:
        """Get total count of images in folder.

        Returns:
            Number of image files found
        """
        return len(self.get_all_images())

    @staticmethod
    def get_filename(file_path: str) -> str:
        """Extract filename from a file path.

        Args:
            file_path: Full or relative file path

        Returns:
            Filename with extension
        """
        return Path(file_path).name
