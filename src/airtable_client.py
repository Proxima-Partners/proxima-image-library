"""Airtable integration for Asset Library."""

import requests
from typing import List, Dict, Optional
from urllib.parse import quote
from src.config import Config


class AirtableClient:
    """Client for interacting with Airtable API."""

    def __init__(self):
        """Initialize Airtable client."""
        self.api_key = Config.AIRTABLE_API_KEY
        self.base_id = Config.AIRTABLE_BASE_ID
        self.table_name = Config.AIRTABLE_TABLE_NAME
        encoded_table_name = quote(self.table_name, safe="")
        self.base_url = f"https://api.airtable.com/v0/{self.base_id}/{encoded_table_name}"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def get_records(self, limit: int = 100) -> List[Dict]:
        """Fetch records from Airtable.

        Args:
            limit: Maximum number of records to fetch

        Returns:
            List of record dictionaries
        """
        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params={"maxRecords": limit},
            )
            response.raise_for_status()
            return response.json().get("records", [])
        except requests.exceptions.RequestException as e:
            print(f"Error fetching records from Airtable: {e}")
            return []

    def record_exists(self, filename: str) -> bool:
        """Check if a record with given filename exists.

        Args:
            filename: Name of the image file

        Returns:
            True if record exists, False otherwise
        """
        records = self.get_records(limit=100)
        for record in records:
            fields = record.get("fields", {})
            if fields.get("Filename") == filename:
                return True
        return False

    def create_record(
        self,
        filename: str,
        image_url: Optional[str] = None,
        alt_text: str = "",
        tags: str = "",
        status: str = "pending-review",
    ) -> Optional[Dict]:
        """Create a new record in Airtable.

        Args:
            filename: Name of the image file
            image_url: URL or path to the image
            alt_text: Alt text for the image
            tags: Comma-separated tags
            status: Status of the record (pending, reviewed, etc.)

        Returns:
            Created record or None if creation failed
        """
        try:
            data = {
                "records": [
                    {
                        "fields": {
                            "Filename": filename,
                            "Alt Text": alt_text,
                            "Tags": tags,
                            "Status": status,
                        }
                    }
                ]
            }
            if image_url:
                data["records"][0]["fields"]["Image"] = [{"url": image_url}]

            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=data,
            )
            response.raise_for_status()
            return response.json().get("records", [None])[0]
        except requests.exceptions.RequestException as e:
            print(f"Error creating record in Airtable: {e}")
            return None

    def get_all_record_ids(self) -> List[str]:
        """Fetch all record IDs from Airtable, handling pagination."""
        record_ids = []
        offset = None
        while True:
            params = {"fields[]": "Filename"}
            if offset:
                params["offset"] = offset
            try:
                response = requests.get(self.base_url, headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()
                for record in data.get("records", []):
                    record_ids.append(record["id"])
                offset = data.get("offset")
                if not offset:
                    break
            except requests.exceptions.RequestException as e:
                print(f"Error fetching record IDs: {e}")
                break
        return record_ids

    def delete_records(self, record_ids: List[str]) -> int:
        """Delete records by ID in batches of 10 (Airtable limit).

        Returns:
            Number of records deleted.
        """
        deleted = 0
        for i in range(0, len(record_ids), 10):
            batch = record_ids[i : i + 10]
            params = [("records[]", rid) for rid in batch]
            try:
                response = requests.delete(self.base_url, headers=self.headers, params=params)
                response.raise_for_status()
                deleted += len(response.json().get("records", batch))
            except requests.exceptions.RequestException as e:
                print(f"Error deleting batch starting at {i}: {e}")
        return deleted

    def delete_all_records(self) -> int:
        """Delete every record in the table. Returns count of deleted records."""
        print("Fetching all record IDs...")
        ids = self.get_all_record_ids()
        print(f"Found {len(ids)} records. Deleting...")
        deleted = self.delete_records(ids)
        print(f"Deleted {deleted} records.")
        return deleted

    def update_record(self, record_id: str, alt_text: str, status: str = "reviewed") -> bool:
        """Update an existing record's alt text.

        Args:
            record_id: Airtable record ID
            alt_text: New alt text
            status: New status

        Returns:
            True if update successful, False otherwise
        """
        try:
            url = f"{self.base_url}/{record_id}"
            data = {
                "fields": {
                    "Alt Text": alt_text,
                    "Status": status,
                }
            }
            response = requests.patch(
                url,
                headers=self.headers,
                json=data,
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error updating record in Airtable: {e}")
            return False
