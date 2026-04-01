"""Main script for Asset Library - orchestrates image processing and Airtable sync."""

import sys
from pathlib import Path
from typing import List

from src.config import Config
from src.image_scanner import ImageScanner
from src.ai_generator import AltTextGenerator
from src.airtable_client import AirtableClient


class AssetLibrary:
    """Main orchestrator for asset library operations."""

    def __init__(self):
        """Initialize the asset library with all components."""
        try:
            Config.validate()
        except ValueError as e:
            print(f"Configuration error: {e}")
            sys.exit(1)

        self.scanner = ImageScanner()
        self.generator = AltTextGenerator()
        self.airtable = AirtableClient()

    def sync_new_images(self, dry_run: bool = False) -> int:
        """Scan for new images and add them to Airtable with alt text.

        Args:
            dry_run: If True, don't actually modify Airtable, just show what would happen

        Returns:
            Number of images processed
        """
        print("🔍 Scanning for images...")
        all_images = self.scanner.get_all_images()
        print(f"Found {len(all_images)} total images")

        # Get existing records from Airtable
        existing_records = self.airtable.get_records(limit=100)
        processed_filenames = {record["fields"].get("Filename") for record in existing_records}

        # Find new images
        new_images = [
            (full_path, relative_path)
            for full_path, relative_path in all_images
            if Path(relative_path).name not in processed_filenames
        ]

        if not new_images:
            print("✅ No new images to process")
            return 0

        print(f"\n📸 Found {len(new_images)} new images to process")

        processed_count = 0
        for i, (full_path, relative_path) in enumerate(new_images, 1):
            filename = Path(relative_path).name
            print(f"\n[{i}/{len(new_images)}] Processing: {filename}")

            # Generate alt text
            print("  ⏳ Generating alt text...")
            alt_text = self.generator.generate_alt_text(full_path)

            if not alt_text:
                print(f"  ❌ Failed to generate alt text")
                continue

            print(f"  ✍️  Alt text: {alt_text}")

            # Create Airtable record
            if not dry_run:
                print("  📤 Uploading to Airtable...")
                record = self.airtable.create_record(
                    filename=filename,
                    alt_text=alt_text,
                    status="pending-review",
                )

                if record:
                    print(f"  ✅ Record created: {record.get('id')}")
                    processed_count += 1
                else:
                    print(f"  ❌ Failed to create Airtable record")
            else:
                print("  🔍 [DRY RUN] Would create Airtable record")
                processed_count += 1

        print(f"\n✨ Processing complete! {processed_count} images synced.")
        return processed_count

    def regenerate_alt_text(self, filename: str, context: str = None) -> bool:
        """Regenerate alt text for a specific image.

        Args:
            filename: Name of the image file
            context: Optional context for better alt text generation

        Returns:
            True if successful, False otherwise
        """
        # Find the image file
        all_images = self.scanner.get_all_images()
        image_path = None

        for full_path, relative_path in all_images:
            if Path(relative_path).name == filename:
                image_path = full_path
                break

        if not image_path:
            print(f"Image not found: {filename}")
            return False

        # Generate new alt text
        print(f"Regenerating alt text for {filename}...")
        alt_text = self.generator.generate_alt_text(image_path, context)

        if not alt_text:
            print("Failed to generate alt text")
            return False

        print(f"New alt text: {alt_text}")

        # Find and update the Airtable record
        records = self.airtable.get_records(limit=100)
        for record in records:
            if record["fields"].get("Filename") == filename:
                success = self.airtable.update_record(record["id"], alt_text)
                if success:
                    print("✅ Record updated in Airtable")
                    return True
                else:
                    print("❌ Failed to update Airtable record")
                    return False

        print(f"Record not found in Airtable: {filename}")
        return False

    def list_images_status(self) -> None:
        """List all images and their processing status."""
        print("📋 Image Status Report\n")

        scanner = ImageScanner()
        all_images = scanner.get_all_images()
        records = self.airtable.get_records(limit=100)

        processed_filenames = {record["fields"].get("Filename"): record for record in records}

        # New images
        new_images = [img for img in all_images if Path(img[1]).name not in processed_filenames]

        # Print new images
        if new_images:
            print(f"🆕 New Images ({len(new_images)}):")
            for full_path, relative_path in new_images:
                print(f"   - {relative_path}")

        # Print processed images
        if processed_filenames:
            print(f"\n✅ Processed Images ({len(processed_filenames)}):")
            for filename, record in processed_filenames.items():
                status = record["fields"].get("Status", "unknown")
                alt_text = record["fields"].get("Alt Text", "")[:50]
                print(f"   - {filename} ({status})")
                if alt_text:
                    print(f"     Alt: {alt_text}...")

        print(f"\n📊 Summary:")
        print(f"   Total images: {len(all_images)}")
        print(f"   Processed: {len(processed_filenames)}")
        print(f"   Pending: {len(new_images)}")


def main():
    """Main entry point."""
    library = AssetLibrary()

    # Example: Sync new images
    library.sync_new_images(dry_run=False)

    # Example: List status
    print("\n" + "=" * 50)
    library.list_images_status()


if __name__ == "__main__":
    main()
