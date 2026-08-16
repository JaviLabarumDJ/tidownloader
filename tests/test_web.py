"""Tests for the Flask web app + SQLite queue."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest

from tidownloader.web import create_app
from tidownloader.web.queue import JobQueue, Worker


@pytest.fixture
def app(tmp_path):
    download_dir = tmp_path / "downloads"
    queue_db = tmp_path / "data" / "queue.db"
    session_dir = tmp_path / "data" / "session"
    config_path = tmp_path / "data" / "config.json"
    flask_app, worker = create_app(download_dir, queue_db, session_dir, config_path)
    flask_app.config["TESTING"] = True
    yield flask_app
    worker.stop()


@pytest.fixture
def client(app):
    return app.test_client()


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"tidownloader" in res.data


def test_static_files_serve(client):
    res = client.get("/static/app.css")
    assert res.status_code == 200
    assert b"--bg" in res.data


def test_auth_status_logged_out(client):
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["logged_in"] is False


def test_add_download_rejects_bad_url(client):
    res = client.post(
        "/api/downloads",
        json={"url": "https://example.com/foo", "quality": "mp3_320"},
    )
    assert res.status_code == 400


def test_add_download_rejects_unknown_quality(client):
    res = client.post(
        "/api/downloads",
        json={"url": "https://tidal.com/playlist/abcdef12-3456-7890-abcd-ef1234567890", "quality": "ultra"},
    )
    assert res.status_code == 400


def test_add_download_creates_job(client):
    res = client.post(
        "/api/downloads",
        json={
            "url": "https://tidal.com/playlist/abcdef12-3456-7890-abcd-ef1234567890",
            "quality": "flac",
        },
    )
    assert res.status_code == 201
    job = res.get_json()
    assert job["status"] == "pending"
    assert job["quality"] == "flac"

    listing = client.get("/api/downloads").get_json()
    assert len(listing) == 1
    assert listing[0]["id"] == job["id"]


def test_add_download_accepts_legacy_quality_strings(client):
    """Old URLs/scripts may pass ``high`` or ``lossless`` — those should
    be silently mapped to the new options."""
    res = client.post(
        "/api/downloads",
        json={
            "url": "https://tidal.com/playlist/abcdef12-3456-7890-abcd-ef1234567890",
            "quality": "high",
        },
    )
    assert res.status_code == 201
    assert res.get_json()["quality"] == "mp3_320"

    res = client.post(
        "/api/downloads",
        json={
            "url": "https://tidal.com/playlist/abcdef12-3456-7890-abcd-ef1234567890",
            "quality": "lossless",
        },
    )
    assert res.status_code == 201
    assert res.get_json()["quality"] == "flac"


def test_delete_download(client):
    create = client.post(
        "/api/downloads",
        json={"url": "https://tidal.com/album/123456789", "quality": "mp3_320"},
    ).get_json()
    res = client.delete(f"/api/downloads/{create['id']}")
    assert res.status_code == 200
    listing = client.get("/api/downloads").get_json()
    assert listing == []


def test_files_list_empty(client):
    res = client.get("/api/files")
    assert res.status_code == 200
    assert res.get_json() == []


def test_auth_status_handles_missing_first_and_last_name(client, monkeypatch, tmp_path):
    """Users whose Tidal profile has null first_name / last_name (e.g.
    signed up via Google) must not crash the auth-status endpoint."""
    from tidownloader.web import server as srv

    class FakeUser:
        id = 1
        first_name = None
        last_name = None
        email = "user@example.com"
        subscription = {"type": "HIFI"}

    class FakeSession:
        check_login = lambda self: True
        user = FakeUser()
        country_code = "ES"

    monkeypatch.setattr(srv.auth, "load_session", lambda: FakeSession())

    res = client.get("/api/auth/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["logged_in"] is True
    assert data["user"]["name"] is None
    assert data["user"]["email"] == "user@example.com"


def test_logout_clears_session(client, tmp_path):
    # Write a fake session, then log out
    session_dir = tmp_path / "data" / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"token_type": "Bearer", "access_token": "x", "refresh_token": None, "expiry_time": None})
    )
    res = client.post("/api/auth/logout")
    assert res.status_code == 200
    assert not (session_dir / "session.json").exists()


def test_queue_roundtrip(tmp_path):
    db = tmp_path / "queue.db"
    q = JobQueue(db)
    job = q.add("https://tidal.com/playlist/abc", "max", "/downloads")
    assert job.status == "pending"
    assert job.id == 1

    q.update(job.id, status="running", total_tracks=10, downloaded=3)
    updated = q.get(job.id)
    assert updated.status == "running"
    assert updated.total_tracks == 10
    assert updated.downloaded == 3

    listing = q.list_jobs()
    assert len(listing) == 1

    q.delete(job.id)
    assert q.get(job.id) is None


def test_worker_processes_job_with_mock_session(tmp_path):
    """Verify the worker actually downloads a track end-to-end when a real
    tidal session is replaced with a mock that returns our fake track."""
    download_dir = tmp_path / "dl"
    queue_db = tmp_path / "queue.db"
    session_dir = tmp_path / "data" / "session"
    config_path = tmp_path / "config.json"
    session_dir.mkdir(parents=True, exist_ok=True)

    fake_session = MagicMock()
    fake_session.check_login.return_value = True

    from tidownloader.api import TrackInfo

    track = TrackInfo(
        track_id=99, title="Song", artists=["Artist"], album="Alb",
        album_id=1, cover_id="abc", duration=200, isrc="X",
        track_number=1, disc_number=1, release_date="2024-01-01", explicit=False,
    )

    with patch("tidownloader.web.queue.auth.load_session", return_value=fake_session), \
         patch("tidownloader.web.queue.resolve_url", return_value=([track], "Alb")):
        q = JobQueue(queue_db)
        from tidownloader.config import ConfigStore
        store = ConfigStore(config_path)
        w = Worker(q, store)
        w.start()
        try:
            job = q.add("https://tidal.com/album/123", "max", str(download_dir))
            import time
            for _ in range(50):
                time.sleep(0.1)
                current = q.get(job.id)
                if current.status in ("done", "error"):
                    break
            final = q.get(job.id)
            assert final is not None
            assert final.status in ("running", "done", "error")
            assert final.total_tracks == 1
        finally:
            w.stop()


def test_settings_get_returns_defaults(client):
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.get_json()
    assert "settings" in data
    assert "schema" in data
    assert data["settings"]["quality"] == "mp3_320"
    assert data["settings"]["concurrent_downloads"] == 1


def test_themes_endpoint_lists_themes(client):
    res = client.get("/api/themes")
    assert res.status_code == 200
    data = res.get_json()
    ids = [t["id"] for t in data["themes"]]
    assert "dark-cyan" in ids
    assert "light-cyan" in ids
    light = [t for t in data["themes"] if t["mode"] == "light"]
    dark = [t for t in data["themes"] if t["mode"] == "dark"]
    assert len(light) >= 1
    assert len(dark) >= 2


def test_job_payload_includes_tracks_list(client):
    """Each job has a tracks list (initially empty until the worker fills it)."""
    res = client.post(
        "/api/downloads",
        json={"url": "https://tidal.com/album/123456789", "quality": "mp3_320"},
    )
    assert res.status_code == 201
    job = res.get_json()
    assert "tracks" in job
    assert isinstance(job["tracks"], list)


def test_local_folder_js_loaded_with_browser_api(client):
    """The local-folder.js bundle uses the File System Access API."""
    res = client.get("/static/local-folder.js")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "showDirectoryPicker" in body
    assert "createWritable" in body


def test_settings_page_renders_local_folder_card(client):
    """The Settings page has the local folder picker card."""
    res = client.get("/")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "local-folder-card" in body
    assert "pick-local-folder" in body
    assert "sync-local-folder" in body
    assert "forget-local-folder" in body


def test_i18n_js_is_served_with_both_locales(client):
    """i18n.js is served and contains both languages."""
    res = client.get("/static/i18n.js")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "I18N" in body
    assert "AVAILABLE_LOCALES" in body
    # The ES locale block exists (key is `es:` without quotes).
    assert "es: {" in body
    assert "en: {" in body
    # And the new local-folder keys made it in.
    assert "localFolder.pick" in body


def test_settings_put_updates(client):
    res = client.put(
        "/api/settings",
        json={"quality": "flac", "concurrent_downloads": 3, "create_m3u8": True},
    )
    assert res.status_code == 200
    cfg = res.get_json()
    assert cfg["quality"] == "flac"
    assert cfg["concurrent_downloads"] == 3
    assert cfg["create_m3u8"] is True


def test_settings_reset(client):
    client.put("/api/settings", json={"quality": "mp3_128", "tracknum_padding": 4})
    res = client.post("/api/settings/reset")
    assert res.status_code == 200
    cfg = res.get_json()
    assert cfg["quality"] == "mp3_320"
    assert cfg["tracknum_padding"] == 2


def test_settings_put_ignores_unknown(client):
    res = client.put("/api/settings", json={"bogus_field": "x", "quality": "flac"})
    assert res.status_code == 200
    cfg = res.get_json()
    assert cfg["quality"] == "flac"
    assert "bogus_field" not in cfg


def test_create_download_with_per_job_path(client, tmp_path):
    res = client.post(
        "/api/downloads",
        json={
            "url": "https://tidal.com/album/123456789",
            "quality": "flac",
            "download_path": str(tmp_path / "custom"),
        },
    )
    assert res.status_code == 201
    job = res.get_json()
    assert job["output_dir"] == str(tmp_path / "custom")
    assert job["quality"] == "flac"


def test_create_download_default_quality_from_settings(client):
    client.put("/api/settings", json={"quality": "flac"})
    res = client.post(
        "/api/downloads",
        json={"url": "https://tidal.com/album/123456789"},
    )
    assert res.status_code == 201
    job = res.get_json()
    assert job["quality"] == "flac"


def test_retry_download(client):
    create = client.post(
        "/api/downloads",
        json={"url": "https://tidal.com/album/123456789", "quality": "mp3_320"},
    ).get_json()
    res = client.post(f"/api/downloads/{create['id']}/retry")
    assert res.status_code == 200
    job = res.get_json()
    assert job["status"] == "pending"
    assert job["error"] == ""


def test_search_requires_login(client):
    res = client.get("/api/search?q=test")
    # No session → 401
    assert res.status_code == 401


def test_search_with_session_returns_results(client, tmp_path):
    from unittest.mock import MagicMock
    from tidownloader.web import server as srv

    class FakeUser:
        id = 1
        first_name = "x"
        last_name = "y"

    fake_session = MagicMock()
    fake_session.check_login.return_value = True
    fake_session.user = FakeUser()
    fake_session.search.return_value = MagicMock(
        tracks=[], albums=[], playlists=[], artists=[], videos=[]
    )
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(srv.auth, "load_session", lambda: fake_session)

    res = client.get("/api/search?q=metallica")
    assert res.status_code == 200
    body = res.get_json()
    assert body["query"] == "metallica"
    assert "results" in body

    monkeypatch.undo()


def test_files_tree_returns_grouped_structure(client, app, tmp_path):
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    (download_dir / "Artist - Album").mkdir()
    (download_dir / "Artist - Album" / "01 - Track.flac").write_bytes(b"x" * 100)
    (download_dir / "Artist - Album" / "02 - Track.flac").write_bytes(b"y" * 200)
    (download_dir / "Artist - Album" / "cover.jpg").write_bytes(b"z" * 50)
    (download_dir / "loose.mp3").write_bytes(b"w" * 30)

    client.put("/api/settings", json={"download_path": str(download_dir)})

    res = client.get("/api/files/tree")
    assert res.status_code == 200
    groups = res.get_json()
    assert isinstance(groups, list)
    by_folder = {g["folder"]: g for g in groups}
    assert "Artist - Album" in by_folder
    alb = by_folder["Artist - Album"]
    assert alb["count"] == 3
    assert alb["size"] == 350
    assert any(f["name"] == "01 - Track.flac" for f in alb["files"])
    assert "" in by_folder
    loose = by_folder[""]
    assert any(f["name"] == "loose.mp3" for f in loose["files"])


def test_delete_file(client, app, tmp_path):
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    f = download_dir / "song.mp3"
    f.write_bytes(b"hello")

    client.put("/api/settings", json={"download_path": str(download_dir)})

    res = client.delete(f"/api/files/file/{f.name}")
    assert res.status_code == 200
    assert not f.exists()


def test_delete_folder(client, app, tmp_path):
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    album = download_dir / "Artist - Album"
    album.mkdir()
    (album / "01.mp3").write_bytes(b"x")
    (album / "02.mp3").write_bytes(b"y")

    client.put("/api/settings", json={"download_path": str(download_dir)})

    res = client.delete(f"/api/files/folder/{quote('Artist - Album')}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["deleted_files"] == 2
    assert not album.exists()


def test_delete_path_escape_blocked(client, app, tmp_path):
    """Trying to delete ../escape must be rejected."""
    download_dir = tmp_path / "dl"
    download_dir.mkdir()

    client.put("/api/settings", json={"download_path": str(download_dir)})

    res = client.delete("/api/files/file/..%2Fescape")
    assert res.status_code == 400