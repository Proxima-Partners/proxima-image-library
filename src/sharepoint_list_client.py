"""SharePoint List client — drop-in replacement for AirtableClient using Microsoft Graph API."""

import os
from typing import Dict, List, Optional

import requests

from src.sharepoint_client import SharePointClient


class SharePointListClient(SharePointClient):
    """Stores image metadata in a SharePoint List via Microsoft Graph API.

    Implements the same interface as AirtableClient so the rest of the app
    needs no changes when switching from Airtable to SharePoint.

    Expected SharePoint List columns (internal names):
        Title           — Filename  (built-in required field, repurposed)
        AltText         — Alt Text
        Tags            — Tags
        Status          — Status
        Slug            — Slug
        Location        — Location  (WebP path, e.g. Headshots/proxima-mike7.webp)
        HighResLocation — High-Res Location
    """

    # App field name → SharePoint internal column name
    _TO_SP = {
        "Filename": "Title",
        "Alt Text": "AltText",
        "Tags": "Tags",
        "Status": "Status",
        "Slug": "Slug",
        "Location": "Location",
        "High-Res Location": "HighResLocation",
    }

    # SharePoint internal column name → app field name
    _TO_APP = {v: k for k, v in _TO_SP.items()}

    def __init__(self):
        super().__init__()
        self.site_id = os.getenv("SHAREPOINT_SITE_ID", "")
        self.list_name = os.getenv("SHAREPOINT_LIST_NAME", "Assets")

    @property
    def _list_url(self) -> str:
        return f"{self.GRAPH_BASE}/sites/{self.site_id}/lists/{self.list_name}"

    def _to_app_record(self, item: dict) -> dict:
        """Normalise a Graph API list item into the app's {id, fields} format."""
        sp_fields = item.get("fields", {})
        fields = {
            app_key: sp_fields.get(sp_key, "") or ""
            for sp_key, app_key in self._TO_APP.items()
        }
        return {"id": str(item["id"]), "fields": fields}

    # ------------------------------------------------------------------
    # Public interface (matches AirtableClient / LocalClient)
    # ------------------------------------------------------------------

    def get_records(self, limit: int = 100) -> List[Dict]:
        url = f"{self._list_url}/items?expand=fields&$top={limit}"
        resp = requests.get(url, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return [self._to_app_record(i) for i in resp.json().get("value", [])]

    def get_all_records(self) -> List[Dict]:
        url = f"{self._list_url}/items?expand=fields&$top=999"
        records = []
        while url:
            resp = requests.get(url, headers=self._headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()
            records.extend(self._to_app_record(i) for i in data.get("value", []))
            url = data.get("@odata.nextLink")
        return records

    def get_all_record_ids(self) -> List[str]:
        url = f"{self._list_url}/items?$select=id&$top=999"
        ids: List[str] = []
        while url:
            resp = requests.get(url, headers=self._headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()
            ids.extend(str(i["id"]) for i in data.get("value", []))
            url = data.get("@odata.nextLink")
        return ids

    def record_exists(self, filename: str) -> bool:
        safe = filename.replace("'", "''")
        url = f"{self._list_url}/items?expand=fields&$filter=fields/Title eq '{safe}'&$top=1"
        resp = requests.get(url, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return len(resp.json().get("value", [])) > 0

    def create_record(
        self,
        filename: str,
        image_url: Optional[str] = None,
        alt_text: str = "",
        tags: str = "",
        status: str = "pending-review",
        slug: str = "",
        location: str = "",
        high_res_location: str = "",
    ) -> Optional[Dict]:
        fields = {
            "Title": filename,
            "AltText": alt_text,
            "Tags": tags,
            "Status": status,
            "Slug": slug,
            "Location": location,
            "HighResLocation": high_res_location,
        }
        try:
            resp = requests.post(
                f"{self._list_url}/items",
                headers=self._headers(),
                json={"fields": fields},
                timeout=15,
            )
            resp.raise_for_status()
            return self._to_app_record(resp.json())
        except requests.exceptions.RequestException as e:
            print(f"Error creating SharePoint list item: {e}")
            return None

    def update_record(self, record_id: str, alt_text: str, status: str = "reviewed") -> bool:
        try:
            resp = requests.patch(
                f"{self._list_url}/items/{record_id}/fields",
                headers=self._headers(),
                json={"AltText": alt_text, "Status": status},
                timeout=15,
            )
            resp.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error updating SharePoint list item {record_id}: {e}")
            return False

    def delete_records(self, record_ids: List[str]) -> int:
        deleted = 0
        for rid in record_ids:
            try:
                resp = requests.delete(
                    f"{self._list_url}/items/{rid}",
                    headers=self._headers(),
                    timeout=15,
                )
                if resp.status_code in (200, 204):
                    deleted += 1
            except requests.exceptions.RequestException as e:
                print(f"Error deleting SharePoint list item {rid}: {e}")
        return deleted

    def delete_all_records(self) -> int:
        print("Fetching all record IDs...")
        ids = self.get_all_record_ids()
        print(f"Found {len(ids)} records. Deleting...")
        deleted = self.delete_records(ids)
        print(f"Deleted {deleted} records.")
        return deleted
