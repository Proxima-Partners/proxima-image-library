"""Flask web app for Proxima Image Library browser."""

import os
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from dotenv import load_dotenv
from typing import List, Optional

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from PIL import Image as PILImage

from src.airtable_client import AirtableClient
from src.local_client import LocalClient
from src.config import Config

load_dotenv()

app = Flask(__name__, template_folder="../templates")

_client = None
_records_cache: Optional[List] = None
_cache_time: float = 0
CACHE_TTL = 300  # 5-minute cache to avoid hammering Airtable API


def get_client():
    global _client
    if _client is None:
        if Config.TEST_MODE:
            _client = LocalClient()
        else:
            _client = AirtableClient()
    return _client


def get_all_records() -> list:
    global _records_cache, _cache_time
    if _records_cache is None or time.time() - _cache_time > CACHE_TTL:
        _records_cache = get_client().get_all_records()
        _cache_time = time.time()
    return _records_cache


@app.route("/")
def launcher():
    return render_template("launcher.html")


@app.route("/library")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------
# Launcher — SSE streaming routes
# ------------------------------------------------------------------

def _stream_command(cmd: list, env: dict = None):
    """Run a command and stream its output as SSE events."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    def generate():
        yield "data: [START]\n\n"
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=run_env,
                cwd=str(Path(__file__).parent.parent),
            )
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    yield f"data: {line}\n\n"
            proc.wait()
            status = "DONE" if proc.returncode == 0 else f"ERROR (exit {proc.returncode})"
            yield f"data: [{status}]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/run/scan-test")
def run_scan_test():
    return _stream_command(
        [sys.executable, "-u", "-m", "src.main"],
        env={"TEST_MODE": "true"},
    )


@app.route("/run/scan-airtable")
def run_scan_airtable():
    return _stream_command([sys.executable, "-u", "-m", "src.main"])


@app.route("/run/clean")
def run_clean():
    mode = request.args.get("mode", "test")
    env = {"TEST_MODE": "true"} if mode == "test" else {}
    script = (
        "from dotenv import load_dotenv; load_dotenv('.env')\n"
        "from src.config import Config\n"
        "from src.local_client import LocalClient\n"
        "from src.airtable_client import AirtableClient\n"
        "import os; os.environ.setdefault('TEST_MODE', '" + ("true" if mode == "test" else "false") + "')\n"
        "client = LocalClient() if Config.TEST_MODE else AirtableClient()\n"
        "client.delete_all_records()\n"
    )
    return _stream_command([sys.executable, "-u", "-c", script], env=env)


@app.route("/api/preview")
def api_preview():
    """Return counts of total images and how many are new (not yet in the store)."""
    mode = request.args.get("mode", "test")
    try:
        from src.image_scanner import ImageScanner
        from src.local_client import LocalClient
        from src.airtable_client import AirtableClient
        from src.config import Config
        import os

        scanner = ImageScanner()
        all_images = scanner.get_all_images()
        total = len(all_images)

        client = LocalClient() if mode == "test" else AirtableClient()
        existing = {r["fields"].get("Filename") for r in client.get_all_records()}

        new_count = sum(
            1 for _, rel in all_images
            if Path(rel).name not in existing
        )
        return jsonify({"total": total, "existing": len(existing), "new": new_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/run/start-server")
def run_start_server():
    """Return a simple redirect instruction — server is already running."""
    return jsonify({"url": "/library"})


@app.route("/run/stop", methods=["POST"])
def run_stop():
    """Shut the server down gracefully after sending the response."""
    import threading, os, signal
    def _shutdown():
        import time
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_shutdown, daemon=True).start()
    return jsonify({"ok": True})


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
