"""Flask web server for tidownloader."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path
from typing import Any

import tidalapi
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from .. import __version__, api
from .. import auth
from ..config import (
    Config,
    ConfigStore,
    OPTION_SCHEMA,
    QUALITY_ORDER,
    QUALITY_OPTIONS,
    resolve_quality_key,
)
from .queue import Job, JobQueue, Worker

LOG = logging.getLogger("tidownloader.web")

THEMES = [
    {"id": "dark-cyan",   "name": "Dark Cyan",    "swatch": "#00d4c5", "mode": "dark"},
    {"id": "dark-magenta","name": "Dark Magenta", "swatch": "#f472b6", "mode": "dark"},
    {"id": "light-cyan",  "name": "Light Cyan",   "swatch": "#0891b2", "mode": "light"},
    {"id": "light-violet","name": "Light Violet", "swatch": "#7c3aed", "mode": "light"},
    {"id": "light-mint",  "name": "Light Mint",   "swatch": "#10b981", "mode": "light"},
]


def _job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "url": job.url,
        "name": job.name,
        "quality": job.quality,
        "status": job.status,
        "total_tracks": job.total_tracks,
        "current_track": job.current_track,
        "current_track_index": job.current_track_index,
        "downloaded": job.downloaded,
        "skipped": job.skipped,
        "failed": job.failed,
        "error": job.error,
        "output_dir": job.output_dir,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "tracks": job.tracks,
    }


def _redirect_session_paths(config_dir: Path) -> None:
    auth.CONFIG_DIR = config_dir
    auth.SESSION_FILE = config_dir / "session.json"


def create_app(
    download_dir: Path,
    queue_db: Path,
    session_dir: Path,
    config_path: Path,
) -> tuple[Flask, Worker]:
    download_dir.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    _redirect_session_paths(session_dir)

    config_store = ConfigStore(config_path)
    cfg = config_store.get()
    # Keep the configured download path in sync with what the user passed.
    cfg.download_path = str(download_dir)
    config_store.update(cfg.to_dict())

    queue = JobQueue(queue_db)
    worker = Worker(queue, config_store)
    worker.start()

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            version=__version__,
            qualities=[
                {"key": k, "label": QUALITY_OPTIONS[k].label,
                 "description": QUALITY_OPTIONS[k].description}
                for k in QUALITY_ORDER
            ],
            option_schema=OPTION_SCHEMA,
        )

    @app.get("/api/health")
    def health() -> Response:
        return jsonify({"status": "ok", "version": __version__})

    @app.get("/api/themes")
    def get_themes() -> Response:
        return jsonify({"themes": THEMES})

    # ---------- Settings ----------

    @app.get("/api/settings")
    def get_settings() -> Response:
        cfg = config_store.get()
        return jsonify({"settings": cfg.to_dict(), "schema": OPTION_SCHEMA})

    @app.put("/api/settings")
    def put_settings() -> Response:
        payload = request.get_json(force=True, silent=True) or {}
        cfg = config_store.update(payload)
        # If download_path changed, ensure it exists.
        Path(cfg.download_path).mkdir(parents=True, exist_ok=True)
        return jsonify(cfg.to_dict())

    @app.post("/api/settings/reset")
    def reset_settings() -> Response:
        cfg = config_store.reset()
        cfg.download_path = str(download_dir)
        config_store.update(cfg.to_dict())
        return jsonify(cfg.to_dict())

    # ---------- Auth ----------

    @app.get("/api/auth/status")
    def auth_status() -> Response:
        session = auth.load_session()
        if session is None:
            return jsonify({"logged_in": False, "user": None})
        try:
            if session.check_login():
                user = session.user
                name = None
                if user:
                    first = getattr(user, "first_name", "") or ""
                    last = getattr(user, "last_name", "") or ""
                    name = (first + " " + last).strip() or None
                return jsonify(
                    {
                        "logged_in": True,
                        "user": {
                            "id": user.id if user else None,
                            "name": name,
                            "email": getattr(user, "email", None) if user else None,
                            "country": session.country_code,
                        }
                        if user
                        else {"country": session.country_code},
                    }
                )
        except Exception:
            LOG.exception("Login check failed")
        return jsonify({"logged_in": False, "user": None})

    @app.post("/api/auth/login")
    def auth_login() -> Response:
        existing = auth.load_session()
        if existing is not None:
            try:
                if existing.check_login():
                    return jsonify({"already_logged_in": True})
            except Exception:
                pass

        session = tidalapi.Session()
        try:
            link_login, future = session.login_oauth()
        except Exception as exc:
            LOG.exception("OAuth start failed")
            return jsonify({"error": f"Failed to start OAuth: {exc}"}), 500

        def _wait_and_save() -> None:
            try:
                future.result()
                if session.access_token:
                    auth.save_session(session)
                    LOG.info("OAuth login completed; session saved")
            except Exception as exc:
                LOG.warning("OAuth login failed: %s", exc)

        threading.Thread(target=_wait_and_save, daemon=True).start()

        return jsonify(
            {
                "verification_uri": link_login.verification_uri_complete,
                "user_code": link_login.user_code,
                "expires_in": link_login.expires_in,
            }
        )

    @app.post("/api/auth/logout")
    def auth_logout() -> Response:
        auth.clear_session()
        return jsonify({"ok": True})

    # ---------- Downloads ----------

    @app.get("/api/downloads")
    def list_downloads() -> Response:
        return jsonify([_job_to_dict(j) for j in queue.list_jobs()])

    @app.post("/api/downloads")
    def create_download() -> Response:
        payload = request.get_json(force=True, silent=True) or {}
        url = (payload.get("url") or "").strip()
        raw_quality = (payload.get("quality") or "").lower()
        custom_dir = (payload.get("download_path") or "").strip()

        if not url:
            return jsonify({"error": "url is required"}), 400

        try:
            api.parse_url(url)
        except Exception as exc:
            return jsonify({"error": f"invalid URL: {exc}"}), 400

        # Resolve legacy / unknown quality strings transparently.
        if raw_quality:
            quality = resolve_quality_key(raw_quality)
            if raw_quality not in QUALITY_OPTIONS and raw_quality not in {"low", "high", "medium", "lossless", "hi_res", "max"}:
                return jsonify({"error": f"unknown quality: {raw_quality}"}), 400
        else:
            quality = config_store.get().quality

        if custom_dir:
            output_dir = custom_dir
        else:
            output_dir = config_store.get().download_path

        job = queue.add(url, quality, output_dir)
        worker.nudge()
        return jsonify(_job_to_dict(job)), 201

    @app.get("/api/downloads/<int:job_id>")
    def get_download(job_id: int) -> Response:
        job = queue.get(job_id)
        if job is None:
            abort(404)
        return jsonify(_job_to_dict(job))

    @app.delete("/api/downloads/<int:job_id>")
    def delete_download(job_id: int) -> Response:
        job = queue.get(job_id)
        if job is None:
            abort(404)
        queue.delete(job_id)
        return jsonify({"ok": True})

    @app.post("/api/downloads/<int:job_id>/retry")
    def retry_download(job_id: int) -> Response:
        job = queue.get(job_id)
        if job is None:
            abort(404)
        queue.update(job_id, status="pending", error="")
        worker.nudge()
        return jsonify(_job_to_dict(job))

    # ---------- Files ----------

    @app.get("/api/files")
    def list_files() -> Response:
        cfg = config_store.get()
        root = Path(cfg.download_path)
        return jsonify(queue.list_files(root))

    @app.get("/api/files/tree")
    def list_files_tree() -> Response:
        cfg = config_store.get()
        root = Path(cfg.download_path)
        return jsonify(queue.list_tree(root))

    @app.get("/api/files/<path:relpath>")
    def download_file(relpath: str) -> Response:
        cfg = config_store.get()
        root = Path(cfg.download_path).resolve()
        target = (root / relpath).resolve()
        if not str(target).startswith(str(root)):
            abort(403)
        if not target.exists() or not target.is_file():
            abort(404)
        return send_from_directory(str(root), relpath, as_attachment=True)

    @app.delete("/api/files/file/<path:relpath>")
    def delete_file(relpath: str) -> Response:
        cfg = config_store.get()
        root = Path(cfg.download_path)
        try:
            ok = queue.delete_file(root, relpath)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not ok:
            return jsonify({"error": "File not found"}), 404
        return jsonify({"ok": True, "deleted": relpath})

    @app.delete("/api/files/folder/<path:relpath>")
    def delete_folder(relpath: str) -> Response:
        cfg = config_store.get()
        root = Path(cfg.download_path)
        try:
            removed = queue.delete_folder(root, relpath)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if removed == 0:
            return jsonify({"error": "Folder not found"}), 404
        return jsonify({"ok": True, "deleted_files": removed, "deleted": relpath})

    # ---------- Search ----------

    @app.get("/api/search")
    def search() -> Response:
        from ..api import search as do_search
        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify({"results": [], "query": ""})
        session = auth.load_session()
        if session is None or not session.check_login():
            return jsonify({"error": "Not logged in"}), 401
        results = do_search(session, q, limit=12)
        return jsonify({"results": results, "query": q})

    return app, worker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tidownloader-web")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--download-dir", default="/downloads")
    parser.add_argument("--queue-db", default="/data/queue.db")
    parser.add_argument("--session-dir", default="/data/session")
    parser.add_argument("--config", default="/data/config.json")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    download_dir = Path(args.download_dir)
    queue_db = Path(args.queue_db)
    session_dir = Path(args.session_dir)
    config_path = Path(args.config)

    app, worker = create_app(download_dir, queue_db, session_dir, config_path)
    try:
        app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False, threaded=True)
    finally:
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())