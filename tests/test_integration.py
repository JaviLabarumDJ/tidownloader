"""Integration test that exercises the full download pipeline with mocks."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from Crypto.Cipher import AES
from Crypto.Util import Counter

from tidownloader.api import TrackInfo, _track_to_info
from tidownloader.config import Config
from tidownloader.downloader import (
    SOURCE_FOR_QUALITY,
    TARGET_EXTENSION_FOR_QUALITY,
    _convert_to_mp3,
    _maybe_postprocess,
    download_track,
    download_tracks,
)
from tidownloader.metadata import target_path_for_track


def _make_fake_stream(segments: list[bytes]):
    """Build a tidalapi Stream-like object with a manifest."""
    init_url = "https://cdn.example/init.mp4"
    segment_urls = [init_url]
    segment_urls.extend(f"https://cdn.example/seg-{i}.m4s" for i in range(1, len(segments) + 1))

    mpd = """<?xml version='1.0' encoding='UTF-8'?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:cenc="urn:mpeg:dash:schema:cenc:2013">
  <Period duration="PT3M45S">
    <AdaptationSet contentType="audio" mimeType="audio/mp4">
      <ContentProtection schemeIdUri="urn:uuid:e2719d58-a985-b3c9-781a-b030af78d30e" value="cenc" cenc:default_KID="12345678-1234-1234-1234-123456789abc"/>
      <Representation id="a" bandwidth="1582020" codecs="flac" samplingRate="44100">
        <BaseURL>https://cdn.example/</BaseURL>
        <SegmentTemplate initialization="init.mp4" media="seg-$Number$.m4s" startNumber="1" timescale="44100"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""
    stream = MagicMock()
    stream.is_mpd = True
    stream.is_bts = False
    stream.manifest = base64.b64encode(mpd.encode("utf-8")).decode("ascii")
    stream.is_encrypted = False
    stream.manifest_mime_type = "application/dash+xml"
    stream.get_manifest_data.return_value = base64.b64decode(stream.manifest).decode("utf-8")

    manifest = MagicMock()
    manifest.urls = segment_urls
    manifest.manifest = stream.manifest
    manifest.manifest_mime_type = stream.manifest_mime_type
    manifest.is_encrypted = False
    manifest.encryption_key = None
    manifest.encryption_type = "NONE"
    manifest.codecs = "FLAC"
    manifest.file_extension = "flac"
    manifest.sample_rate = 44100
    manifest.mime_type = "audio/flac"
    stream.get_stream_manifest.return_value = manifest
    return stream, manifest


def _make_fake_session(track: TrackInfo, encrypted_segments: list[bytes], key: bytes, *, download_dir: Path):
    """Build a Session-like object that responds to chain calls."""
    session = MagicMock()
    session.config.quality = "LOSSLESS"
    session.request_session = MagicMock()

    track_obj = MagicMock()
    track_obj.id = track.track_id
    track_obj.name = track.title
    track_obj.album = MagicMock()
    track_obj.album.name = track.album
    track_obj.album.id = track.album_id
    track_obj.album.cover = track.cover_id
    track_obj.album.release_date = track.release_date
    track_obj.album.upc = "123456789012"
    track_obj.artist = MagicMock()
    track_obj.artist.name = track.artists[0]
    track_obj.artists = [track_obj.artist]
    track_obj.volume_num = track.disc_number
    track_obj.track_num = track.track_number
    track_obj.explicit = track.explicit
    track_obj.isrc = track.isrc
    track_obj.duration = track.duration
    track_obj.lyrics.side_effect = Exception("no lyrics")

    stream_obj, manifest = _make_fake_stream(encrypted_segments)
    track_obj.get_stream.return_value = stream_obj

    session.track.return_value = track_obj
    session.album.return_value = track_obj.album

    key_response = MagicMock()
    key_response.status_code = 200
    key_response.json.return_value = {"key": base64.b64encode(key).decode("ascii")}
    session.request.basic_request.return_value = key_response

    def get(url, stream=True, timeout=60):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if "init.mp4" in url:
            resp.iter_content.return_value = [b"INIT"]
            return resp
        for i, seg in enumerate(encrypted_segments, start=1):
            if f"seg-{i}.m4s" in url:
                resp.iter_content.return_value = [seg]
                return resp
        # Cover art endpoint
        if "resources.tidal.com" in url:
            cover_resp = MagicMock()
            cover_resp.content = b"\xff\xd8\xff"
            cover_resp.raise_for_status = lambda: None
            return cover_resp
        raise AssertionError(f"Unexpected URL: {url}")

    session.request_session.get.side_effect = get
    return session


def test_end_to_end_download(tmp_path: Path):
    key = b"0123456789abcdef"
    plaintext = [b"hello", b"world", b"FLAC"]
    encrypted = []
    for i, p in enumerate(plaintext, start=1):
        ctr = Counter.new(128, initial_value=i)
        encrypted.append(AES.new(key, AES.MODE_CTR, counter=ctr).encrypt(p))

    track = TrackInfo(
        track_id=42, title="Song", artists=["Artist"], album="Alb",
        album_id=1, cover_id="abc-def", duration=200, isrc="X",
        track_number=1, disc_number=1, release_date="2024-01-01",
        explicit=False,
    )
    download_dir = tmp_path / "dl"
    session = _make_fake_session(track, encrypted, key, download_dir=download_dir)

    cfg = Config(download_path=str(download_dir), quality="flac")
    path = download_track(session, track, cfg)

    assert path is not None
    assert path.exists()
    contents = path.read_bytes()
    # Quality "flac" keeps the raw decrypted payload (no MP3 conversion).
    assert contents == b"INIT" + b"".join(plaintext)
    assert path.parent.name == "Artist - Alb"


def test_skip_existing_when_target_present(tmp_path: Path):
    key = b"0123456789abcdef"
    encrypted = [b"hello"]
    track = TrackInfo(
        track_id=42, title="Song", artists=["Artist"], album="Alb",
        album_id=1, cover_id="abc-def", duration=200, isrc="X",
        track_number=1, disc_number=1, release_date="2024-01-01", explicit=False,
    )
    download_dir = tmp_path / "dl"
    session = _make_fake_session(track, encrypted, key, download_dir=download_dir)

    cfg = Config(download_path=str(download_dir), skip_existing=True, quality="flac")

    target, _ = target_path_for_track(track, cfg, "flac")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"PRESERVED")

    path = download_track(session, track, cfg)
    assert path is not None
    assert path.read_bytes() == b"PRESERVED"


def test_overwrite_replaces_existing(tmp_path: Path):
    key = b"0123456789abcdef"
    encrypted = [b"hello"]
    track = TrackInfo(
        track_id=42, title="Song", artists=["Artist"], album="Alb",
        album_id=1, cover_id="abc-def", duration=200, isrc="X",
        track_number=1, disc_number=1, release_date="2024-01-01", explicit=False,
    )
    download_dir = tmp_path / "dl"
    session = _make_fake_session(track, encrypted, key, download_dir=download_dir)

    cfg = Config(
        download_path=str(download_dir),
        skip_existing=True,
        overwrite_existing=True,
        quality="flac",
    )
    target, _ = target_path_for_track(track, cfg, "flac")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"PRESERVED")

    path = download_track(session, track, cfg)
    assert path is not None
    assert path.read_bytes() != b"PRESERVED"


def test_download_tracks_concurrent(tmp_path: Path):
    key = b"0123456789abcdef"
    tracks = []
    encrypted_map = {}
    for i in range(3):
        plaintext = [f"track{i}-seg0".encode(), f"track{i}-seg1".encode()]
        enc = []
        for j, p in enumerate(plaintext, start=1):
            ctr = Counter.new(128, initial_value=j)
            enc.append(AES.new(key, AES.MODE_CTR, counter=ctr).encrypt(p))
        encrypted_map[i] = enc
        tracks.append(TrackInfo(
            track_id=100 + i, title=f"Song {i}", artists=["Artist"], album=f"Album {i}",
            album_id=1, cover_id=f"abc-{i}", duration=200, isrc=f"ISRC{i}",
            track_number=i + 1, disc_number=1, release_date="2024-01-01", explicit=False,
        ))

    download_dir = tmp_path / "dl"
    session = _make_fake_session(tracks[0], encrypted_map[0], key, download_dir=download_dir)
    # Override album responses for other tracks.
    def fake_album(album_id):
        album = MagicMock()
        album.upc = "UPC"
        return album
    session.album.side_effect = fake_album
    session.track.side_effect = lambda tid: _make_fake_session_for_track(tid, tracks, encrypted_map, session)

    cfg = Config(download_path=str(download_dir), concurrent_downloads=2)
    results = download_tracks(session, tracks, cfg)
    assert len(results) == 3
    for (track, path) in results:
        assert path is not None
        assert path.exists()


def _make_fake_session_for_track(tid, tracks, encrypted_map, session):
    idx = tid - 100
    if idx < 0 or idx >= len(tracks):
        return session.track.return_value
    track = tracks[idx]
    encrypted = encrypted_map[idx]
    track_obj = MagicMock()
    track_obj.id = track.track_id
    track_obj.name = track.title
    track_obj.album = MagicMock()
    track_obj.album.name = track.album
    track_obj.album.id = track.album_id
    track_obj.album.cover = track.cover_id
    track_obj.album.release_date = track.release_date
    track_obj.album.upc = "UPC"
    track_obj.artist = MagicMock()
    track_obj.artist.name = track.artists[0]
    track_obj.artists = [track_obj.artist]
    track_obj.volume_num = track.disc_number
    track_obj.track_num = track.track_number
    track_obj.explicit = track.explicit
    track_obj.isrc = track.isrc
    track_obj.duration = track.duration
    track_obj.lyrics.side_effect = Exception("no lyrics")

    stream_obj, manifest = _make_fake_stream(encrypted)
    track_obj.get_stream.return_value = stream_obj
    return track_obj


def test_playlist_filename_template(tmp_path: Path):
    key = b"0123456789abcdef"
    plaintext = [b"x"]
    enc = []
    for j, p in enumerate(plaintext, start=1):
        ctr = Counter.new(128, initial_value=j)
        enc.append(AES.new(key, AES.MODE_CTR, counter=ctr).encrypt(p))
    track = TrackInfo(
        track_id=1, title="S", artists=["A"], album="Alb",
        album_id=1, cover_id="abc", duration=200, isrc="X",
        track_number=1, disc_number=1, release_date="2024-01-01", explicit=False,
    )
    download_dir = tmp_path / "dl"
    session = _make_fake_session(track, enc, key, download_dir=download_dir)

    cfg = Config(
        download_path=str(download_dir),
        quality="flac",
        playlist_filename_template="{playlistnum:03d} - {artist} - {title}",
        playlist_folder_template="Playlists/{playlist}",
        create_playlist_folder=True,
        tracknum_padding=3,
    )
    path = download_track(
        session, track, cfg,
        playlist_name="My Mix", playlist_index=5, playlist_owner="me",
    )
    assert path is not None
    assert "Playlists/My Mix" in str(path)
    assert path.name == "005 - A - S.flac"


def test_quality_maps_to_tidal_api_values():
    """The new single-enum quality must still end up as a valid Tidal
    API value (otherwise Tidal returns 404 like before)."""
    for key in ("mp3_128", "mp3_256", "mp3_320", "m4a"):
        assert SOURCE_FOR_QUALITY[key] == "HIGH"
    assert SOURCE_FOR_QUALITY["flac"] == "HI_RES_LOSSLESS"
    assert TARGET_EXTENSION_FOR_QUALITY["flac"] == "flac"
    for key in ("mp3_128", "mp3_256", "mp3_320"):
        assert TARGET_EXTENSION_FOR_QUALITY[key] == "mp3"
    assert TARGET_EXTENSION_FOR_QUALITY["m4a"] == "m4a"


def test_download_track_sets_tidal_quality_for_mp3_option(tmp_path: Path):
    """``mp3_320`` downloads from Tidal's HIGH (AAC) and converts."""
    key = b"0123456789abcdef"
    plaintext = [b"x"]
    enc = []
    for j, p in enumerate(plaintext, start=1):
        ctr = Counter.new(128, initial_value=j)
        enc.append(AES.new(key, AES.MODE_CTR, counter=ctr).encrypt(p))
    track = TrackInfo(
        track_id=1, title="S", artists=["A"], album="Alb",
        album_id=1, cover_id="abc", duration=200, isrc="X",
        track_number=1, disc_number=1, release_date="2024-01-01", explicit=False,
    )
    download_dir = tmp_path / "dl"
    session = _make_fake_session(track, enc, key, download_dir=download_dir)
    cfg = Config(download_path=str(download_dir), quality="mp3_320")
    download_track(session, track, cfg)
    assert session.config.quality == "HIGH"


def test_download_track_uses_fallback_for_flac(tmp_path: Path):
    """If the primary quality (HI_RES_LOSSLESS) is unavailable, the
    downloader must try LOSSLESS before giving up."""
    key = b"0123456789abcdef"

    # Two calls: first request (HI_RES_LOSSLESS) raises; second
    # (LOSSLESS) succeeds and returns a fake manifest.
    from unittest.mock import MagicMock
    session = MagicMock()
    session.config.quality = None
    session.request_session = MagicMock()
    session.request_session.get.return_value.iter_content.return_value = [b"INIT"]
    session.request_session.get.return_value.raise_for_status = lambda: None

    call_count = {"n": 0}

    def fake_get_stream():
        call_count["n"] += 1
        if call_count["n"] == 1:
            from tidalapi.exceptions import StreamNotAvailable
            raise StreamNotAvailable("hi-res not available")
        stream, manifest = _make_fake_stream([])
        return stream

    track_obj = MagicMock()
    track_obj.get_stream.side_effect = fake_get_stream
    session.track.return_value = track_obj

    key_response = MagicMock()
    key_response.status_code = 200
    key_response.json.return_value = {"key": base64.b64encode(key).decode("ascii")}
    session.request.basic_request.return_value = key_response

    # Empty manifest -> track skipped; we just want to verify the fallback
    # was attempted.
    track = TrackInfo(
        track_id=1, title="S", artists=["A"], album="Alb",
        album_id=1, cover_id="abc", duration=200, isrc="X",
        track_number=1, disc_number=1, release_date="2024-01-01", explicit=False,
    )
    cfg = Config(download_path=str(tmp_path / "dl"), quality="flac")
    download_track(session, track, cfg)
    assert call_count["n"] == 2, "fallback was not attempted"
    # The session quality ended up at LOSSLESS (the fallback value).
    assert session.config.quality == "LOSSLESS"


def test_real_tidal_track_has_volume_num_not_disc_num():
    """Regression for the production bug: tidalapi.Track exposes
    ``volume_num`` for the disc number, not ``disc_num``. The converter
    must use ``getattr`` to remain backward-compatible."""
    fake_album = MagicMock(spec=["name", "id", "cover", "release_date"])
    fake_album.name = "Album"
    fake_album.id = 1
    fake_album.cover = "abc-def"
    fake_album.release_date = None

    fake_artist = MagicMock(spec=["name"])
    fake_artist.name = "Artist"

    full_track = MagicMock(spec=[
        "id", "name", "album", "artist", "artists",
        "volume_num", "track_num", "isrc", "explicit", "duration",
    ])
    full_track.id = 1
    full_track.name = "Song"
    full_track.album = fake_album
    full_track.artist = fake_artist
    full_track.artists = [fake_artist]
    full_track.volume_num = 2
    full_track.track_num = 5
    full_track.isrc = "X"
    full_track.explicit = False
    full_track.duration = 200

    info = _track_to_info(full_track)
    assert info.disc_number == 2
    assert info.track_number == 5


def test_maybe_postprocess_noop_for_m4a_quality(tmp_path: Path):
    src = tmp_path / "song.m4a"
    src.write_bytes(b"x")
    tgt = tmp_path / "song.m4a"
    out = _maybe_postprocess(src, tgt, "m4a", "m4a")
    assert out == tgt


def test_maybe_postprocess_noop_for_flac_quality(tmp_path: Path):
    """FLAC stays FLAC regardless of what the manifest reports."""
    src = tmp_path / "song.flac"
    src.write_bytes(b"x")
    tgt = tmp_path / "song.flac"
    out = _maybe_postprocess(src, tgt, "flac", "flac")
    assert out == tgt


def test_maybe_postprocess_skips_when_delivered_flac(tmp_path: Path):
    """If Tidal delivered FLAC but user asked for MP3, don't transcode."""
    src = tmp_path / "song.flac"
    src.write_bytes(b"x")
    tgt = tmp_path / "song.mp3"
    out = _maybe_postprocess(src, tgt, "flac", "mp3_320")
    assert out == tgt


def test_maybe_postprocess_handles_missing_ffmpeg(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tidownloader.downloader.shutil.which", lambda x: None)
    src = tmp_path / "song.m4a"
    src.write_bytes(b"x")
    tgt = tmp_path / "song.mp3"
    out = _maybe_postprocess(src, tgt, "m4a", "mp3_320")
    # Without ffmpeg we fall back to renaming source → target.
    assert out == tgt
    assert tgt.exists()


def test_convert_to_mp3_invokes_ffmpeg(tmp_path: Path, monkeypatch):
    """Smoke test: ensure the ffmpeg command is built correctly."""
    calls = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"fake mp3 data")
        return FakeResult()

    monkeypatch.setattr("tidownloader.downloader.shutil.which", lambda x: "/usr/bin/ffmpeg")
    monkeypatch.setattr("tidownloader.downloader.subprocess.run", fake_run)

    src = tmp_path / "song.m4a"
    tgt = tmp_path / "song.mp3"
    src.write_bytes(b"x")
    out = _convert_to_mp3(src, tgt, 320)
    assert out is not None
    assert out.exists()
    assert out.name == "song.mp3"
    assert "-codec:a" in calls["cmd"]
    assert "libmp3lame" in calls["cmd"]
    assert "320k" in calls["cmd"]