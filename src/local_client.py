"""Local JSON-backed table used in TEST_MODE — mirrors AirtableClient interface."""

import json
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional


_DEFAULT_PATH = Path(__file__).parent.parent / "test_data" / "local_table.json"
_LOCK = threading.Lock()  # serialise concurrent reads/writes across all LocalClient instances


class LocalClient:
    """Drop-in replacement for AirtableClient that stores records in a local JSON file."""

    def __init__(self, db_path: Path = _DEFAULT_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._save([])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> List[Dict]:
        with self.db_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, records: List[Dict]) -> None:
        tmp = self.db_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        tmp.replace(self.db_path)

    def patch_fields(self, record_id: str, fields: Dict) -> bool:
        """Thread-safe update of arbitrary fields on a record."""
        with _LOCK:
            records = self._load()
            for r in records:
                if r["id"] == record_id:
                    r["fields"].update(fields)
                    self._save(records)
                    return True
        return False

    # ------------------------------------------------------------------
    # Public interface (matches AirtableClient)
    # ------------------------------------------------------------------

    def get_records(self, limit: int = 100) -> List[Dict]:
        return self._load()[:limit]

    def get_all_records(self) -> List[Dict]:
        return self._load()

    def get_all_record_ids(self) -> List[str]:
        return [r["id"] for r in self._load()]

    def record_exists(self, filename: str) -> bool:
        return any(r["fields"].get("Filename") == filename for r in self._load())

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
        records = self._load()
        record = {
            "id": f"loc_{uuid.uuid4().hex[:14]}",
            "fields": {
                "Filename": filename,
                "Alt Text": alt_text,
                "Tags": tags,
                "Status": status,
                "Slug": slug,
                "Location": location,
                "High-Res Location": high_res_location,
            },
        }
        if image_url:
            record["fields"]["Image"] = [{"url": image_url}]
        records.append(record)
        self._save(records)
        return record

    def update_record(self, record_id: str, alt_text: str, status: str = "reviewed") -> bool:
        records = self._load()
        for r in records:
            if r["id"] == record_id:
                r["fields"]["Alt Text"] = alt_text
                r["fields"]["Status"] = status
                self._save(records)
                return True
        return False


    def delete_records(self, record_ids: List[str]) -> int:
        records = self._load()
        id_set = set(record_ids)
        kept = [r for r in records if r["id"] not in id_set]
        self._save(kept)
        return len(records) - len(kept)

    def delete_all_records(self) -> int:
        records = self._load()
        self._save([])
        count = len(records)
        print(f"Deleted {count} local records.")
        return count
