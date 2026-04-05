"""Flask web app for Proxima Image Library browser."""

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
from typing import Dict, List, Optional
from werkzeug.utils import secure_filename

import functools

import msal
import requests
from flask import Flask, Response, jsonify, redirect, render_template, request, session, stream_with_context, url_for
from flask_cors import CORS
from PIL import Image as PILImage

from src.local_client import LocalClient
from src.config import Config

load_dotenv()

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = Config.FLASK_SECRET_KEY

# Allow configured origins to call the API (Webflow frontend + localhost dev)
CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}},
     supports_credentials=False)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _msal_app():
    return msal.ConfidentialClientApplication(
        Config.MSAL_CLIENT_ID,
        authority=Config.MSAL_AUTHORITY,
        client_credential=Config.MSAL_CLIENT_SECRET,
    )


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "Authentication required"}), 401
            session["next"] = request.url
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login")
def login():
    flow = _msal_app().initiate_auth_code_flow(
        Config.MSAL_SCOPES,
        redirect_uri=Config.MSAL_REDIRECT_URI,
    )
    session["auth_flow"] = flow
    return redirect(flow["auth_uri"])


@app.route("/auth/callback")
def auth_callback():
    try:
        result = _msal_app().acquire_token_by_auth_code_flow(
            session.get("auth_flow", {}),
            request.args,
        )
        if "error" in result:
            return render_template("login_error.html", error=result.get("error_description", "Authentication failed")), 401
        session["user"] = result.get("id_token_claims", {})
    except Exception as e:
        return render_template("login_error.html", error=str(e)), 401

    next_url = session.pop("next", url_for("index"))
    return redirect(next_url)


@app.route("/logout")
def logout():
    session.clear()
    logout_url = (
        f"{Config.MSAL_AUTHORITY}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={url_for('index', _external=True)}"
    )
    return redirect(logout_url)

_client = None
_sp_client = None
_records_cache: Optional[List] = None
_cache_time: float = 0
CACHE_TTL = 300  # 5-minute cache


def get_client():
    global _client
    if _client is None:
        if Config.TEST_MODE:
            _client = LocalClient()
        else:
            from src.sharepoint_list_client import SharePointListClient
            _client = SharePointListClient()
    return _client


def get_sp_client():
    global _sp_client
    if _sp_client is None:
        from src.sharepoint_client import SharePointClient
        _sp_client = SharePointClient()
    return _sp_client


def get_all_records() -> list:
    global _records_cache, _cache_time
    if _records_cache is None or time.time() - _cache_time > CACHE_TTL:
        _records_cache = get_client().get_all_records()
        _cache_time = time.time()
    return _records_cache


@app.route("/health")
@app.route("/healthz")
def health():
    return jsonify({"status": "ok"})


@app.route("/")
@app.route("/library")
@login_required
def index():
    return render_template("index.html", user=session.get("user", {}))


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


@app.route("/stock-search")
@login_required
def stock_search():
    return render_template("stock_search.html")


@app.route("/api/parse-suggestions", methods=["POST"])
def api_parse_suggestions():
    data = request.get_json(force=True)
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "No content provided"}), 400
    from src.stock_client import parse_photo_suggestions
    phrases = parse_photo_suggestions(content)
    return jsonify({"phrases": phrases})


@app.route("/api/stock-search", methods=["POST"])
def api_stock_search():
    data = request.get_json(force=True)
    phrases = data.get("phrases", [])
    limit = max(1, min(int(data.get("limit", 12)), 20))
    if not phrases:
        return jsonify({"error": "No phrases provided"}), 400
    phrases = phrases[:20]
    from src.stock_client import search_all_libraries
    results = search_all_libraries(phrases, limit)
    return jsonify({"results": results})


_DOWNLOAD_ALLOWED_DOMAINS = {
    "images.pexels.com",
    "www.pexels.com",
    "cdn.pixabay.com",
    "pixabay.com",
    "images.unsplash.com",
}


def _stock_source_context(source: str, title: str, tags: list[str], photographer: str) -> str:
    """Build a context string from stock API metadata to pass to Claude."""
    parts = []
    if source:
        parts.append(f"Source: {source}")
    if title:
        parts.append(f"Title from source: {title}")
    if photographer:
        parts.append(f"Photographer: {photographer}")
    if tags:
        parts.append(f"Keywords from source: {', '.join(tags)}")
    if not parts:
        return ""
    return (
        "\n".join(parts) + "\n\n"
        "Use the above source metadata as a starting point. "
        "Reconcile keywords against the approved tag vocabulary — keep matches, drop anything off-vocabulary."
    )


@app.route("/api/catalog-stock")
@login_required
def api_catalog_stock():
    """SSE stream — download a stock image and run the full pipeline with source metadata as context."""
    download_url = request.args.get("download_url", "").strip()
    filename     = request.args.get("filename", "image.jpg").strip() or "image.jpg"
    dl_location  = request.args.get("dl", "").strip()   # Unsplash attribution ping
    source       = request.args.get("source", "").strip()
    title        = request.args.get("title", "").strip()
    tags_raw     = request.args.get("tags", "").strip()
    photographer = request.args.get("photographer", "").strip()
    category     = request.args.get("category", "").strip() or None

    from src.image_processor import CATEGORIES, process_image

    if not download_url:
        return jsonify({"error": "download_url required"}), 400

    domain = urlparse(download_url).netloc.lower()
    if not any(domain == d or domain.endswith("." + d) for d in _DOWNLOAD_ALLOWED_DOMAINS):
        return jsonify({"error": "URL not permitted"}), 403

    if category is not None and category not in CATEGORIES:
        return jsonify({"error": f"Invalid category. Must be one of: {CATEGORIES}"}), 400

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    source_context = _stock_source_context(source, title, tags, photographer)

    def generate():
        yield "data: [START]\n\n"
        q: queue.Queue = queue.Queue()

        def worker():
            try:
                # Unsplash attribution ping
                if dl_location:
                    dl_domain = urlparse(dl_location).netloc.lower()
                    if "unsplash.com" in dl_domain:
                        access_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
                        if access_key:
                            try:
                                requests.get(dl_location, headers={"Authorization": f"Client-ID {access_key}"}, timeout=5)
                            except Exception:
                                pass

                q.put(("progress", f"Downloading from {source or 'source'}…"))
                resp = requests.get(download_url, timeout=30)
                resp.raise_for_status()
                file_bytes = resp.content

                from src.ai_generator import AltTextGenerator
                gen = AltTextGenerator()

                if Config.TEST_MODE:
                    list_client = LocalClient()
                    sp_client = None
                    storage_mode = "local"
                else:
                    from src.sharepoint_list_client import SharePointListClient
                    from src.sharepoint_client import SharePointClient
                    list_client = SharePointListClient()
                    sp_client = SharePointClient()
                    storage_mode = "sharepoint"

                result = process_image(
                    file_bytes=file_bytes,
                    original_filename=filename,
                    generator=gen,
                    list_client=list_client,
                    sp_client=sp_client,
                    image_folder=Config.IMAGE_FOLDER,
                    storage_mode=storage_mode,
                    on_progress=lambda msg: q.put(("progress", msg)),
                    category=category,
                    source_context=source_context or None,
                )
                q.put(("done", result))
            except Exception as exc:
                q.put(("error", str(exc)))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while True:
            try:
                kind, value = q.get(timeout=180)
            except queue.Empty:
                yield "data: [ERROR] Processing timed out after 3 minutes\n\n"
                break

            if kind == "progress":
                yield f"data: {value}\n\n"
            elif kind == "done":
                import json as _json
                yield f"data: [RESULT] {_json.dumps(value)}\n\n"
                yield "data: [DONE]\n\n"
                break
            elif kind == "error":
                yield f"data: [ERROR] {value}\n\n"
                break

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/download-image")
@login_required
def api_download_image():
    """Proxy-download a stock image so the browser gets a file attachment."""
    url = request.args.get("url", "").strip()
    filename = request.args.get("filename", "image.jpg").strip() or "image.jpg"
    download_location = request.args.get("dl", "").strip()  # Unsplash attribution ping

    if not url:
        return jsonify({"error": "url required"}), 400

    # Restrict to known stock-photo CDN domains only
    domain = urlparse(url).netloc.lower()
    if not any(domain == d or domain.endswith("." + d) for d in _DOWNLOAD_ALLOWED_DOMAINS):
        return jsonify({"error": "URL not permitted"}), 403

    # Unsplash attribution: fire-and-forget ping to their download endpoint
    if download_location:
        dl_domain = urlparse(download_location).netloc.lower()
        if "unsplash.com" in dl_domain:
            access_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
            if access_key:
                try:
                    requests.get(
                        download_location,
                        headers={"Authorization": f"Client-ID {access_key}"},
                        timeout=5,
                    )
                except Exception:
                    pass

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    return Response(
        resp.content,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
        },
    )


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
        status = fields.get("Status", "")
        status_filter = request.args.get("status", "")
        if status_filter and status != status_filter:
            continue
        if not selected_tags or (rec_tags & selected_tags):
            results.append(
                {
                    "id": rec["id"],
                    "filename": fields.get("Filename", ""),
                    "location": location,
                    "alt_text": fields.get("Alt Text", ""),
                    "tags": fields.get("Tags", ""),
                    "status": status,
                }
            )
    return jsonify({"images": results})


@app.route("/api/pending-count")
@login_required
def api_pending_count():
    records = get_all_records()
    count = sum(1 for r in records if r.get("fields", {}).get("Status") == "pending-review")
    return jsonify({"count": count})


@app.route("/api/image-status", methods=["PATCH"])
@login_required
def api_image_status():
    data = request.get_json(force=True) or {}
    record_id = data.get("id", "").strip()
    status = data.get("status", "").strip()
    alt_text = data.get("alt_text")  # optional

    valid_statuses = {"pending-review", "approved", "rejected", "archived"}
    if not record_id:
        return jsonify({"error": "id required"}), 400
    if status not in valid_statuses:
        return jsonify({"error": f"status must be one of {sorted(valid_statuses)}"}), 400

    fields: dict = {"Status": status}
    if alt_text is not None:
        fields["Alt Text"] = alt_text.strip()

    if Config.TEST_MODE:
        ok = LocalClient().patch_fields(record_id, fields)
    else:
        from src.sharepoint_list_client import SharePointListClient
        ok = SharePointListClient().patch_fields(record_id, fields)

    if ok:
        global _records_cache
        _records_cache = None  # invalidate so pending-count reflects the change
        return jsonify({"ok": True})
    return jsonify({"error": "Record not found or update failed"}), 404


@app.route("/review")
@login_required
def review():
    return render_template("review.html", user=session.get("user", {}))


@app.route("/api/image-info")
def api_image_info():
    location = unquote(request.args.get("path", ""))
    if not location:
        return jsonify({"error": "Missing path"}), 400

    if Config.STORAGE_MODE == "sharepoint":
        try:
            root = Config.SHAREPOINT_IMAGE_FOLDER
            webp_path = f"{root}/WebP/{location}" if root else f"WebP/{location}"
            meta = get_sp_client().get_file_metadata(webp_path)
            file_bytes = meta.get("size", 0)
            if file_bytes >= 1_048_576:
                file_size = f"{file_bytes / 1_048_576:.1f} MB"
            elif file_bytes >= 1024:
                file_size = f"{file_bytes / 1024:.1f} KB"
            else:
                file_size = f"{file_bytes} B"
            image_facet = meta.get("image", {})
            width = image_facet.get("width", 0)
            height = image_facet.get("height", 0)
            return jsonify({"width": width, "height": height, "file_size": file_size})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

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
@login_required
def thumbnail():
    return _serve_image(thumb=True)


@app.route("/image")
@login_required
def image():
    return _serve_image(thumb=False)




_sp_url_cache: dict[str, tuple[str, float]] = {}  # key → (url, expires_at)
_SP_URL_TTL = 2700  # 45 minutes (SharePoint CDN URLs expire ~1 hour)


def _get_sp_url(sp_path: str, thumb: bool) -> str:
    """Return a SharePoint CDN URL, using a short-lived cache to avoid repeated Graph API calls."""
    cache_key = f"{'thumb' if thumb else 'full'}:{sp_path}"
    cached = _sp_url_cache.get(cache_key)
    if cached and cached[1] > time.time():
        return cached[0]
    url = get_sp_client().get_thumbnail_url(sp_path) if thumb else get_sp_client().get_file_url(sp_path)
    _sp_url_cache[cache_key] = (url, time.time() + _SP_URL_TTL)
    return url


def _serve_image(thumb: bool) -> Response:
    location = unquote(request.args.get("path", ""))
    if not location:
        return Response("Missing path parameter", status=400)

    if Config.STORAGE_MODE == "sharepoint":
        try:
            root = Config.SHAREPOINT_IMAGE_FOLDER
            sp_path = f"{root}/WebP/{location}" if root else f"WebP/{location}"
            url = _get_sp_url(sp_path, thumb)
            return redirect(url)
        except Exception as e:
            return Response(f"Error: {e}", status=500)

    image_folder = Path(os.getenv("IMAGE_FOLDER", "./assets")).resolve()

    # Prefer WebP/ subdirectory (aligned with SharePoint convention); fall back to
    # direct path for legacy records that pre-date this convention.
    full_path = None
    for candidate in [image_folder / "WebP" / location, image_folder / location]:
        resolved = candidate.resolve()
        if str(resolved).startswith(str(image_folder)) and resolved.exists():
            full_path = resolved
            break

    if full_path is None:
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


# ------------------------------------------------------------------
# Tag library
# ------------------------------------------------------------------

@app.route("/tag-manager")
@login_required
def tag_manager():
    return render_template("tag_manager.html")


@app.route("/api/tag-library", methods=["GET"])
def api_tag_library_get():
    from src.tag_library import TagLibrary
    return jsonify(TagLibrary.instance().get_all())


@app.route("/api/tag-library/suggestions")
def api_tag_library_suggestions():
    """Return all ?suggested tags found across existing records."""
    records = get_all_records()
    suggestions: dict = {}  # tag → count
    for rec in records:
        for tag in rec.get("fields", {}).get("Tags", "").split(","):
            tag = tag.strip()
            if tag.startswith("?"):
                suggestions[tag] = suggestions.get(tag, 0) + 1
    return jsonify({"suggestions": [
        {"tag": t, "count": c} for t, c in sorted(suggestions.items())
    ]})


@app.route("/api/tag-library/add", methods=["POST"])
def api_tag_library_add():
    data = request.get_json(force=True)
    tag      = data.get("tag", "").strip()
    category = data.get("category", "Custom").strip()
    if not tag:
        return jsonify({"error": "tag required"}), 400
    from src.tag_library import TagLibrary
    TagLibrary.instance().add_tag(tag, category)
    return jsonify({"ok": True})


@app.route("/api/tag-library/remove", methods=["POST"])
def api_tag_library_remove():
    data = request.get_json(force=True)
    tag = data.get("tag", "").strip()
    if not tag:
        return jsonify({"error": "tag required"}), 400
    from src.tag_library import TagLibrary
    found = TagLibrary.instance().remove_tag(tag)
    return jsonify({"ok": found})


@app.route("/api/tag-library/promote", methods=["POST"])
def api_tag_library_promote():
    """Promote a ?suggested tag to an approved tag."""
    data     = request.get_json(force=True)
    tag      = data.get("tag", "").strip()
    category = data.get("category", "Custom").strip()
    if not tag:
        return jsonify({"error": "tag required"}), 400
    from src.tag_library import TagLibrary
    TagLibrary.instance().promote_suggestion(tag, category)
    TagLibrary.instance().invalidate_cache()
    return jsonify({"ok": True})


# ------------------------------------------------------------------
# Feature 2: Catalog external images via upload
# ------------------------------------------------------------------

_UPLOAD_ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _staged_lookup(file_id: str) -> Optional[Dict[str, str]]:
    """Find a staged temp file by ID from the filesystem (worker-safe)."""
    matches = list(Path(tempfile.gettempdir()).glob(f"proxima_{file_id}__*"))
    if not matches:
        return None
    path = matches[0]
    # Filename is encoded after the double-underscore separator
    filename = path.name[len(f"proxima_{file_id}__"):]
    return {"path": str(path), "filename": filename}


def _staged_save(file_id: str, original_name: str, data: bytes) -> str:
    """Write file bytes to a temp path encoding the original name in the filename."""
    tmp_path = Path(tempfile.gettempdir()) / f"proxima_{file_id}__{original_name}"
    tmp_path.write_bytes(data)
    return str(tmp_path)


@app.route("/upload")
@login_required
def upload():
    return render_template("upload.html")


@app.route("/api/upload/stage", methods=["POST"])
def api_upload_stage():
    """Receive multipart file upload, save to temp, return staged IDs."""
    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No files provided"}), 400

    staged = []
    for f in files:
        original_name = secure_filename(f.filename or "upload")
        ext = Path(original_name).suffix.lower()
        if ext not in _UPLOAD_ALLOWED:
            staged.append({"error": f"Unsupported format: {ext or '(none)'}", "filename": original_name})
            continue

        file_id = uuid.uuid4().hex
        _staged_save(file_id, original_name, f.read())
        staged.append({"id": file_id, "filename": original_name})

    return jsonify({"staged": staged})


@app.route("/api/upload/process")
def api_upload_process():
    """SSE stream — run the full pipeline for one staged file."""
    file_id = request.args.get("id", "")
    category = request.args.get("category", "") or None  # None = AI determines it

    from src.image_processor import CATEGORIES, process_image
    staged = _staged_lookup(file_id)
    if staged is None:
        return jsonify({"error": "Unknown or expired file ID"}), 404
    if category is not None and category not in CATEGORIES:
        return jsonify({"error": f"Invalid category. Must be one of: {CATEGORIES}"}), 400

    def generate():
        yield "data: [START]\n\n"
        q: queue.Queue = queue.Queue()

        def worker():
            try:
                file_bytes = Path(staged["path"]).read_bytes()
                try:
                    os.unlink(staged["path"])
                except OSError:
                    pass

                from src.ai_generator import AltTextGenerator
                gen = AltTextGenerator()

                if Config.TEST_MODE:
                    list_client = LocalClient()
                    sp_client = None
                    storage_mode = "local"
                else:
                    from src.sharepoint_list_client import SharePointListClient
                    from src.sharepoint_client import SharePointClient
                    list_client = SharePointListClient()
                    sp_client = SharePointClient()
                    storage_mode = "sharepoint"

                result = process_image(
                    file_bytes=file_bytes,
                    original_filename=staged["filename"],
                    generator=gen,
                    list_client=list_client,
                    sp_client=sp_client,
                    image_folder=Config.IMAGE_FOLDER,
                    storage_mode=storage_mode,
                    on_progress=lambda msg: q.put(("progress", msg)),
                    category=category,
                )
                q.put(("done", result))
            except Exception as exc:
                q.put(("error", str(exc)))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while True:
            try:
                kind, value = q.get(timeout=180)
            except queue.Empty:
                yield "data: [ERROR] Processing timed out after 3 minutes\n\n"
                break

            if kind == "progress":
                yield f"data: {value}\n\n"
            elif kind == "done":
                yield f"data: [RESULT] {json.dumps(value)}\n\n"
                yield "data: [DONE]\n\n"
                # Invalidate records cache so library reflects new image
                global _records_cache
                _records_cache = None
                break
            elif kind == "error":
                yield f"data: [ERROR] {value}\n\n"
                break

        t.join(timeout=5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Shutterstock quota tracking
# ---------------------------------------------------------------------------

SS_QUOTA_LIMIT = 10
# /home persists on Azure App Service; fall back to project root locally
_SS_COUNTER_PATH = Path(
    "/home/proxima_ss_counter.json"
    if Path("/home").exists() and os.getenv("WEBSITE_INSTANCE_ID")
    else "proxima_ss_counter.json"
)
_ss_lock = threading.Lock()


def _ss_read() -> dict:
    """Return {month: 'YYYY-MM', count: int}."""
    try:
        if _SS_COUNTER_PATH.exists():
            return json.loads(_SS_COUNTER_PATH.read_text())
    except Exception:
        pass
    return {"month": "", "count": 0}


def _ss_write(data: dict) -> None:
    _SS_COUNTER_PATH.write_text(json.dumps(data))


@app.route("/api/shutterstock/quota")
@login_required
def api_ss_quota():
    with _ss_lock:
        data = _ss_read()
        current_month = time.strftime("%Y-%m")
        if data.get("month") != current_month:
            data = {"month": current_month, "count": 0}
    return jsonify({"used": data["count"], "limit": SS_QUOTA_LIMIT, "month": data["month"]})


@app.route("/api/shutterstock/track", methods=["POST"])
@login_required
def api_ss_track():
    with _ss_lock:
        data = _ss_read()
        current_month = time.strftime("%Y-%m")
        if data.get("month") != current_month:
            data = {"month": current_month, "count": 0}
        data["count"] += 1
        _ss_write(data)
    return jsonify({"used": data["count"], "limit": SS_QUOTA_LIMIT})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
