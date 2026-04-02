"""Flask web app for Proxima Image Library browser."""

import os
import time
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from dotenv import load_dotenv
from typing import List, Optional

from flask import Flask, Response, jsonify, render_template, request
from PIL import Image as PILImage

from src.airtable_client import AirtableClient

load_dotenv()

app = Flask(__name__, template_folder="../templates")

_client: Optional[AirtableClient] = None
_records_cache: Optional[List] = None
_cache_time: float = 0
CACHE_TTL = 300  # 5-minute cache to avoid hammering Airtable API


def get_client() -> AirtableClient:  # type: ignore[return]
    global _client
    if _client is None:
        _client = AirtableClient()
    return _client


def get_all_records() -> list:
    global _records_cache, _cache_time
    if _records_cache is None or time.time() - _cache_time > CACHE_TTL:
        _records_cache = get_client().get_all_records()
        _cache_time = time.time()
    return _records_cache


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/folders")
def api_folders():
    records = get_all_records()
    folder_counts: dict = {}
    for rec in records:
        location = rec.get("fields", {}).get("Location", "")
        folder = str(PurePosixPath(location).parent) if location else "."
        folder_counts[folder] = folder_counts.get(folder, 0) + 1
    folders = [
        {"name": f, "count": c}
        for f, c in sorted(folder_counts.items())
    ]
    return jsonify({"folders": folders})


@app.route("/api/tags")
def api_tags():
    folder = request.args.get("folder", "")
    records = get_all_records()
    tag_set: set = set()
    for rec in records:
        fields = rec.get("fields", {})
        if folder:
            location = fields.get("Location", "")
            rec_folder = str(PurePosixPath(location).parent) if location else "."
            if rec_folder != folder:
                continue
        tags_str = fields.get("Tags", "")
        for tag in tags_str.split(","):
            tag = tag.strip()
            if tag:
                tag_set.add(tag)
    return jsonify({"tags": sorted(tag_set, key=str.lower)})


@app.route("/api/images")
def api_images():
    folder = request.args.get("folder", "")
    selected = request.args.get("tags", "")
    selected_tags = {t.strip() for t in selected.split(",") if t.strip()}
    records = get_all_records()
    results = []
    for rec in records:
        fields = rec.get("fields", {})
        location = fields.get("Location", "")
        if folder:
            rec_folder = str(PurePosixPath(location).parent) if location else "."
            if rec_folder != folder:
                continue
        rec_tags = {t.strip() for t in fields.get("Tags", "").split(",") if t.strip()}
        if not selected_tags or (rec_tags & selected_tags):
            results.append(
                {
                    "id": rec["id"],
                    "filename": fields.get("Filename", ""),
                    "location": location,
                    "alt_text": fields.get("Alt Text", ""),
                    "tags": fields.get("Tags", ""),
                }
            )
    return jsonify({"images": results})


@app.route("/api/image-info")
def api_image_info():
    location = unquote(request.args.get("path", ""))
    if not location:
        return jsonify({"error": "Missing path"}), 400

    image_folder = Path(os.getenv("IMAGE_FOLDER", "./assets")).resolve()
    full_path = (image_folder / location).resolve()

    if not str(full_path).startswith(str(image_folder)):
        return jsonify({"error": "Forbidden"}), 403

    if not full_path.exists():
        return jsonify({"error": "Not found"}), 404

    try:
        file_bytes = full_path.stat().st_size
        if file_bytes >= 1_048_576:
            file_size = f"{file_bytes / 1_048_576:.1f} MB"
        elif file_bytes >= 1024:
            file_size = f"{file_bytes / 1024:.1f} KB"
        else:
            file_size = f"{file_bytes} B"

        with PILImage.open(full_path) as img:
            width, height = img.size

        return jsonify({"width": width, "height": height, "file_size": file_size})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/thumbnail")
def thumbnail():
    return _serve_image(thumb=True)


@app.route("/image")
def image():
    return _serve_image(thumb=False)


def _serve_image(thumb: bool) -> Response:
    location = unquote(request.args.get("path", ""))
    if not location:
        return Response("Missing path parameter", status=400)

    image_folder = Path(os.getenv("IMAGE_FOLDER", "./assets")).resolve()
    full_path = (image_folder / location).resolve()

    # Prevent path traversal
    if not str(full_path).startswith(str(image_folder)):
        return Response("Forbidden", status=403)

    if not full_path.exists():
        return Response("Image not found", status=404)

    try:
        img = PILImage.open(full_path)
        if thumb:
            img.thumbnail((240, 240))
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return Response(buf.read(), mimetype="image/jpeg")
    except Exception as e:
        return Response(f"Error reading image: {e}", status=500)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
