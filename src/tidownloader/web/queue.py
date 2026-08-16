"""SQLite-backed job queue + background worker.

Each job now carries a per-track progress list so the UI can render
real-time status for every track (pending → downloading → done / failed
/ skipped), including the segment-level percentage.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import tidalapi

from .. import api, auth, downloader
from ..api import TrackInfo, resolve_url
from ..config import Config, ConfigStore

LOG = logging.getLogger("tidownloader.web.queue")


@dataclass
class TrackProgress:
    track_id: int
    title: str
    artists: list[str]
    status: str = "pending"          # pending | downloading | done | failed | skipped
    progress_pct: int = 0            # 0-100, segments downloaded within this track
    bytes_done: int = 0
    bytes_total: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "title": self.title,
            "artists": self.artists,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "error": self.error,
        }


@dataclass
class Job:
    id: int
    url: str
    name: str
    quality: str
    status: str
    total_tracks: int
    current_track: str
    current_track_index: int
    downloaded: int
    skipped: int
    failed: int
    error: str
    output_dir: str
    created_at: str
    updated_at: str
    tracks: list[dict] = field(default_factory=list)


def _row_to_job(row: sqlite3.Row) -> Job:
    try:
        tracks_raw = row["tracks_json"]
        tracks = json.loads(tracks_raw) if tracks_raw else []
    except Exception:
        tracks = []
    return Job(
        id=row["id"],
        url=row["url"],
        name=row["name"],
        quality=row["quality"],
        status=row["status"],
        total_tracks=row["total_tracks"],
        current_track=row["current_track"] or "",
        current_track_index=row["current_track_index"] or 0,
        downloaded=row["downloaded"] or 0,
        skipped=row["skipped"] or 0,
        failed=row["failed"] or 0,
        error=row["error"] or "",
        output_dir=row["output_dir"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        tracks=tracks,
    )


class JobQueue:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        quality TEXT NOT NULL DEFAULT 'max',
        status TEXT NOT NULL DEFAULT 'pending',
        total_tracks INTEGER NOT NULL DEFAULT 0,
        current_track TEXT NOT NULL DEFAULT '',
        current_track_index INTEGER NOT NULL DEFAULT 0,
        downloaded INTEGER NOT NULL DEFAULT 0,
        skipped INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        output_dir TEXT NOT NULL DEFAULT '/downloads',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        tracks_json TEXT NOT NULL DEFAULT '[]'
    );
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(self.SCHEMA)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "skipped" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN skipped INTEGER NOT NULL DEFAULT 0")
            if "tracks_json" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN tracks_json TEXT NOT NULL DEFAULT '[]'")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def add(self, url: str, quality: str, output_dir: str) -> Job:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO jobs (url, quality, status, output_dir, created_at, updated_at, tracks_json)"
                " VALUES (?, ?, 'pending', ?, ?, ?, '[]')",
                (url, quality, output_dir, now, now),
            )
            job_id = cur.lastrowid
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row)

    def get(self, job_id: int) -> Optional[Job]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self) -> list[Job]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT 200"
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def list_files(self, root: Path) -> list[dict]:
        if not root.exists():
            return []
        files: list[dict] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append(
                {
                    "path": str(path.relative_to(root)),
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
        files.sort(key=lambda f: f["modified"], reverse=True)
        return files

    def list_tree(self, root: Path) -> list[dict]:
        """Return a tree view: top-level folders, each containing files.

        Items at the root of ``root`` are listed under a synthetic folder
        named "Root" so they can be removed as a group.
        """
        if not root.exists():
            return []

        groups: dict[str, list[dict]] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root)
            parts = rel.parts
            folder = "/".join(parts[:-1]) if len(parts) > 1 else ""
            groups.setdefault(folder, []).append(
                {
                    "path": str(rel),
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )

        tree: list[dict] = []
        # Sort: folders with subdirs first, then by name. Empty folder names (root files) last.
        for folder in sorted(groups.keys(), key=lambda f: (f == "", f)):
            files = sorted(groups[folder], key=lambda f: f["name"].lower())
            tree.append({
                "folder": folder,
                "name": folder.split("/")[-1] if folder else "Loose files",
                "files": files,
                "count": len(files),
                "size": sum(f["size"] for f in files),
            })
        return tree

    def delete_file(self, root: Path, relpath: str) -> bool:
        target = (root / relpath).resolve()
        if not str(target).startswith(str(root.resolve())):
            raise ValueError("Path escapes download root")
        if not target.exists() or not target.is_file():
            return False
        target.unlink()
        return True

    def delete_folder(self, root: Path, relpath: str) -> int:
        target = (root / relpath).resolve()
        root_resolved = root.resolve()
        if not str(target).startswith(str(root_resolved)):
            raise ValueError("Path escapes download root")
        if not target.exists() or not target.is_dir():
            return 0
        # Count files before deleting.
        removed = sum(1 for p in target.rglob("*") if p.is_file())
        import shutil
        shutil.rmtree(target)
        return removed

    def update(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        columns = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [job_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)

    def update_tracks(self, job_id: int, tracks: list[dict]) -> None:
        """Replace the per-track progress list."""
        payload = json.dumps(tracks, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET tracks_json = ?, updated_at = ? WHERE id = ?",
                (payload, _now(), job_id),
            )

    def delete(self, job_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Worker:
    def __init__(self, queue: JobQueue, config_store: ConfigStore):
        self.queue = queue
        self.config_store = config_store
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="td-worker", daemon=True)
        self._thread.start()
        LOG.info("Worker thread started")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def nudge(self) -> None:
        self._wake.set()

    def _next_pending(self) -> Optional[Job]:
        with self.queue._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status IN ('pending', 'running')"
                " ORDER BY id ASC LIMIT 1"
            ).fetchone()
        return _row_to_job(row) if row else None

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._next_pending()
            if job is None:
                self._wake.wait(timeout=5)
                self._wake.clear()
                continue
            self._process(job)

    # ------------------------------------------------------------------ #
    # Job processing
    # ------------------------------------------------------------------ #

    def _process(self, job: Job) -> None:
        LOG.info("Processing job %s: %s", job.id, job.url)
        cfg = self.config_store.get()
        if job.output_dir and job.output_dir != cfg.download_path:
            cfg.download_path = job.output_dir
        if job.quality:
            cfg.quality = job.quality

        out_path = Path(cfg.download_path)
        if not out_path.exists():
            try:
                out_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                LOG.warning("Cannot use download path %s: %s", out_path, exc)
                self.queue.update(
                    job.id,
                    status="error",
                    error=f"Download path is not writable: {out_path} ({exc}). "
                          "If you're using Docker, the path must be inside a "
                          "bind-mounted volume (e.g. /downloads).",
                )
                return
        if not os.access(out_path, os.W_OK):
            self.queue.update(job.id, status="error", error=f"Download path is not writable: {out_path}")
            return

        session = auth.load_session()
        if session is None or not session.check_login():
            self.queue.update(job.id, status="error", error="Not logged in. Visit Settings to log in.")
            return

        try:
            tracks_meta, name = resolve_url(session, job.url)
        except Exception as exc:
            LOG.exception("Resolve failed for job %s", job.id)
            self.queue.update(job.id, status="error", error=f"Resolve failed: {exc}")
            return

        is_playlist = "playlist" in job.url

        # Build per-track progress list.
        track_progresses: list[TrackProgress] = [
            TrackProgress(
                track_id=t.track_id,
                title=t.title,
                artists=list(t.artists),
            )
            for t in tracks_meta
        ]

        self.queue.update(
            job.id,
            status="running",
            name=name,
            total_tracks=len(tracks_meta),
            current_track="",
            current_track_index=0,
            downloaded=0,
            skipped=0,
            failed=0,
            error="",
        )
        self.queue.update_tracks(job.id, [t.to_dict() for t in track_progresses])

        downloaded = 0
        skipped = 0
        failed = 0
        last_error = ""
        lock = threading.Lock()
        job_started_at = datetime.now().timestamp()

        def _save_track(idx: int, **fields: Any) -> None:
            for k, v in fields.items():
                setattr(track_progresses[idx], k, v)
            self.queue.update_tracks(job.id, [t.to_dict() for t in track_progresses])

        def _on_segment(c: int, total: int, track_id: int) -> None:
            # Find the track by id and update its percentage.
            for i, tp in enumerate(track_progresses):
                if tp.track_id == track_id:
                    pct = int((c / total) * 100) if total else 0
                    _save_track(i, progress_pct=pct, bytes_done=c, bytes_total=total)
                    break

        def _per_track(idx: int, track: TrackInfo) -> None:
            nonlocal downloaded, skipped, failed, last_error
            tp = track_progresses[idx]
            with lock:
                tp.status = "downloading"
                tp.progress_pct = 0
                tp.error = ""
            self.queue.update_tracks(job.id, [t.to_dict() for t in track_progresses])
            self.queue.update(
                job.id,
                current_track=track.title,
                current_track_index=idx + 1,
            )

            try:
                path = downloader.download_track(
                    session,
                    track,
                    cfg,
                    on_progress=lambda c, total: _on_segment(c, total, track.track_id),
                    playlist_name=name if is_playlist else "",
                    playlist_index=(idx + 1) if is_playlist else None,
                    playlist_owner=getattr(session.user, "username", "") if session.user else "",
                )
            except Exception as exc:
                LOG.exception("Track download failed")
                err = f"{track.title}: {exc}"[:300]
                with lock:
                    failed += 1
                    last_error = err
                    tp.status = "failed"
                    tp.error = err
                    self.queue.update(job.id, failed=failed, error=last_error)
                self.queue.update_tracks(job.id, [t.to_dict() for t in track_progresses])
                return

            with lock:
                if path is None:
                    failed += 1
                    err = f"{track.title}: stream not available"
                    last_error = err
                    tp.status = "failed"
                    tp.error = err
                    self.queue.update(job.id, failed=failed, error=last_error)
                elif path.exists() and path.stat().st_mtime < job_started_at - 1:
                    skipped += 1
                    tp.status = "skipped"
                    tp.progress_pct = 100
                    self.queue.update(job.id, skipped=skipped)
                else:
                    downloaded += 1
                    tp.status = "done"
                    tp.progress_pct = 100
                    self.queue.update(job.id, downloaded=downloaded)
            self.queue.update_tracks(job.id, [t.to_dict() for t in track_progresses])

        # Run tracks (serially or in parallel based on cfg.concurrent_downloads).
        workers = max(1, min(cfg.concurrent_downloads, len(tracks_meta)))
        if workers == 1:
            for i, t in enumerate(tracks_meta):
                _per_track(i, t)
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_per_track, i, t) for i, t in enumerate(tracks_meta)]
                for f in futures:
                    f.result()

        if cfg.create_m3u8 and is_playlist and tracks_meta:
            try:
                self._write_m3u8(cfg, name, tracks_meta)
            except Exception as exc:
                LOG.warning("M3U8 write failed: %s", exc)

        if cfg.remove_finished and failed == 0:
            self.queue.delete(job.id)
        else:
            final_status = "error" if downloaded == 0 and skipped == 0 and failed > 0 else "done"
            self.queue.update(
                job.id,
                status=final_status,
                current_track="",
                current_track_index=len(tracks_meta),
                error=last_error if final_status == "error" else "",
            )

    def _write_m3u8(self, cfg: Config, name: str, tracks: list[TrackInfo]) -> None:
        from ..metadata import write_m3u8
        out_dir = Path(cfg.download_path)
        entries = []
        for t in tracks:
            from ..metadata import target_path_for_track
            try:
                target, folder_rel = target_path_for_track(
                    t, cfg, extension="flac",
                    playlist_name=name, playlist_index=tracks.index(t) + 1,
                )
                rel = target.parent.relative_to(out_dir).as_posix()
                entries.append((rel, target.name))
            except Exception:
                continue
        write_m3u8(out_dir, "", entries, cfg, name)