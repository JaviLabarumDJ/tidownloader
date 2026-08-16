"""Unit tests for tidownloader helpers."""

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from Crypto.Cipher import AES
from Crypto.Util import Counter

from tidownloader import auth, config as cfg_module
from tidownloader.api import TrackInfo, parse_url
from tidownloader.config import (
    Config,
    ConfigStore,
    DEFAULT_QUALITY,
    QUALITY_OPTIONS,
    QUALITY_ORDER,
    resolve_quality_key,
)
from tidownloader.manifest import (
    _extract_kid,
    _extract_scheme,
    _split_segments,
    decrypt_segment,
)
from tidownloader.templates import (
    RenderContext,
    build_folder_and_filename,
    render,
    sanitize,
)


# ---------- URL parsing ----------


@pytest.mark.parametrize("url,kind", [
    ("https://tidal.com/playlist/abcdef12-3456-7890-abcd-ef1234567890", "playlist"),
    ("https://tidal.com/album/123456789", "album"),
    ("https://tidal.com/track/123456789", "track"),
    ("https://tidal.com/browse/playlist/abcdef12-3456-7890-abcd-ef1234567890", "playlist"),
    ("https://tidal.com/mix/track/abcdef12-3456-7890-abcd-ef1234567890", "mix"),
    ("https://listen.tidal.com/album/123456789", "album"),
    ("https://tidal.com/artist/123456789", "artist"),
])
def test_parse_url(url, kind):
    assert parse_url(url)[0] == kind


def test_parse_url_rejects_non_tidal():
    with pytest.raises(ValueError):
        parse_url("https://spotify.com/playlist/abc")


def test_parse_url_rejects_unknown_path():
    with pytest.raises(ValueError):
        parse_url("https://tidal.com/random/123")


# ---------- Quality ----------


def test_default_quality_is_mp3_320():
    assert DEFAULT_QUALITY == "mp3_320"
    assert Config().quality == "mp3_320"


def test_quality_options_have_expected_keys():
    assert set(QUALITY_ORDER) == {"mp3_128", "mp3_256", "mp3_320", "m4a", "flac"}


def test_quality_options_map_to_tidal_values():
    assert QUALITY_OPTIONS["mp3_128"].tidal_quality == "HIGH"
    assert QUALITY_OPTIONS["mp3_256"].tidal_quality == "HIGH"
    assert QUALITY_OPTIONS["mp3_320"].tidal_quality == "HIGH"
    assert QUALITY_OPTIONS["m4a"].tidal_quality == "HIGH"
    assert QUALITY_OPTIONS["flac"].tidal_quality == "HI_RES_LOSSLESS"
    assert QUALITY_OPTIONS["flac"].fallback == "LOSSLESS"


def test_mp3_quality_options_have_bitrate_in_description():
    """Sanity: each MP3 option must mention its kbps in the label."""
    for k in ("mp3_128", "mp3_256", "mp3_320"):
        label = QUALITY_OPTIONS[k].label
        assert str({"mp3_128": "128", "mp3_256": "256", "mp3_320": "320"}[k]) in label


def test_resolve_quality_key_handles_legacy_strings():
    assert resolve_quality_key("max") == "mp3_320"
    assert resolve_quality_key("hi_res") == "flac"
    assert resolve_quality_key("lossless") == "flac"
    assert resolve_quality_key("low") == "mp3_128"
    assert resolve_quality_key("") == "mp3_320"
    assert resolve_quality_key("nonsense") == "mp3_320"
    assert resolve_quality_key("MP3_320") == "mp3_320"
    assert resolve_quality_key("flac") == "flac"
    assert resolve_quality_key("m4a") == "m4a"


def test_config_validates_legacy_quality():
    cfg = Config(quality="max")
    cfg._validate()
    assert cfg.quality == "mp3_320"


def test_config_rejects_unknown_quality():
    cfg = Config(quality="not-a-thing")
    cfg._validate()
    assert cfg.quality == "mp3_320"


# ---------- Manifest parsing ----------


MPD = """<?xml version='1.0' encoding='UTF-8'?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:cenc="urn:mpeg:dash:schema:cenc:2013">
  <Period duration="PT3M45S">
    <AdaptationSet contentType="audio" mimeType="audio/mp4">
      <ContentProtection schemeIdUri="urn:uuid:e2719d58-a985-b3c9-781a-b030af78d30e" value="cenc" cenc:default_KID="12345678-1234-1234-1234-123456789abc"/>
      <Representation id="a" bandwidth="1582020" codecs="flac" samplingRate="44100">
        <BaseURL>https://sp-abc.stream.tidal.com/abc</BaseURL>
        <SegmentTemplate initialization="$RepresentationID$/init.mp4" media="$RepresentationID$/$Number$.m4s" startNumber="1" timescale="44100"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""


def test_extract_kid_removes_dashes():
    assert _extract_kid(MPD) == "12345678123412341234123456789abc"


def test_extract_scheme_cenc():
    assert _extract_scheme(MPD) == "cenc"


def test_extract_scheme_cbcs():
    cbcs = MPD.replace('"cenc"', '"cbcs"')
    assert _extract_scheme(cbcs) == "cbcs"


def test_split_segments_separates_init():
    init, segments = _split_segments(["u-init", "u-1", "u-2"])
    assert init == "u-init"
    assert segments == ["u-1", "u-2"]


# ---------- Decryption ----------


def test_decrypt_segment_ctr_roundtrip():
    key = b"0123456789abcdef"
    plaintext = b"FLAC AUDIO PAYLOAD" * 4
    ctr = Counter.new(128, initial_value=7)
    ct = AES.new(key, AES.MODE_CTR, counter=ctr).encrypt(plaintext)
    assert decrypt_segment(key, 7, "cenc", ct) == plaintext


def test_decrypt_segment_cbcs_only_first_16_bytes():
    key = b"0123456789abcdef"
    plaintext_head = b"FLAC__HEADER!!!X"
    plaintext_tail = b"AFTER_HEADER"
    iv = (1).to_bytes(16, "big")
    cbc = AES.new(key, AES.MODE_CBC, iv=iv)
    ct = cbc.encrypt(plaintext_head) + plaintext_tail
    out = decrypt_segment(key, 1, "cbcs", ct)
    assert out == plaintext_head + plaintext_tail


# ---------- Auth serialization ----------


def test_session_to_dict_serializes_datetime():
    session = MagicMock()
    session.access_token = "abc"
    session.token_type = "Bearer"
    session.refresh_token = "xyz"
    session.expiry_time = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    data = auth._session_to_dict(session)
    assert data["access_token"] == "abc"
    assert isinstance(data["expiry_time"], str)

    encoded = json.dumps(data, default=auth._json_default)
    decoded = json.loads(encoded)
    assert decoded["expiry_time"] == "2026-12-31T23:59:59+00:00"


def test_session_to_dict_handles_naive_datetime():
    session = MagicMock()
    session.access_token = "abc"
    session.token_type = "Bearer"
    session.refresh_token = None
    session.expiry_time = datetime(2026, 1, 1, 0, 0, 0)

    data = auth._session_to_dict(session)
    assert data["expiry_time"].endswith("+00:00")


def test_session_to_dict_handles_none_expiry():
    session = MagicMock()
    session.access_token = "abc"
    session.token_type = "Bearer"
    session.refresh_token = None
    session.expiry_time = None

    data = auth._session_to_dict(session)
    assert data["expiry_time"] is None


def test_coerce_datetime_accepts_string_and_datetime():
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert auth._coerce_datetime(dt) is dt
    assert auth._coerce_datetime(dt.isoformat()) == dt
    assert auth._coerce_datetime(None) is None
    assert auth._coerce_datetime("not-a-date") is None


# ---------- Config dataclass ----------


def test_config_defaults_are_valid():
    cfg = Config()
    cfg._validate()
    assert cfg.quality == "mp3_320"
    assert cfg.concurrent_downloads == 1


def test_config_validates_quality():
    cfg = Config(quality="bogus")
    cfg._validate()
    assert cfg.quality == "mp3_320"


def test_config_clamps_concurrent_downloads():
    cfg = Config(concurrent_downloads=999)
    cfg._validate()
    assert cfg.concurrent_downloads == cfg.max_workers


def test_config_round_trips_through_dict():
    cfg = Config(quality="flac", concurrent_downloads=2)
    data = cfg.to_dict()
    cfg2 = Config.from_dict(data)
    assert cfg2.quality == "flac"
    assert cfg2.concurrent_downloads == 2


def test_config_store_persists(tmp_path: Path):
    path = tmp_path / "cfg.json"
    store = cfg_module.ConfigStore(path)
    store.update({"quality": "flac", "tracknum_padding": 3})
    cfg = ConfigStore(path).get()
    assert cfg.quality == "flac"
    assert cfg.tracknum_padding == 3


def test_config_store_resets(tmp_path: Path):
    path = tmp_path / "cfg.json"
    store = cfg_module.ConfigStore(path)
    store.update({"quality": "mp3_128"})
    store.reset()
    assert ConfigStore(path).get().quality == "mp3_320"


def test_config_store_ignores_unknown_keys(tmp_path: Path):
    path = tmp_path / "cfg.json"
    store = cfg_module.ConfigStore(path)
    store.update({"nonexistent_field": "x", "quality": "m4a"})
    cfg = ConfigStore(path).get()
    assert cfg.quality == "m4a"


# ---------- Templates ----------


def _track(**kw):
    defaults = dict(
        track_id=1, title="Title", artists=["Artist"], album="Album",
        album_id=10, cover_id="abc", duration=200, isrc="USRC",
        track_number=3, disc_number=1, release_date="2024-05-12",
        explicit=False,
    )
    defaults.update(kw)
    return TrackInfo(**defaults)


def test_render_replaces_simple_variable():
    ctx = RenderContext(title="Hello", artist="X")
    assert render("{title} - {artist}", ctx) == "Hello - X"


def test_render_formats_tracknum_with_padding():
    ctx = RenderContext(tracknum="03")
    assert render("{tracknum:02d}", ctx) == "03"


def test_render_handles_missing_variables():
    ctx = RenderContext(title="Hello")
    assert render("{title}-{artist}", ctx) == "Hello-"


def test_sanitize_strips_unsafe_chars():
    cfg = Config()
    assert sanitize('a/b\\c:d|e?f*g"h<i>j', cfg) == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_truncates_long_names():
    cfg = Config(max_filename_length=20)
    long = "a" * 50
    assert len(sanitize(long, cfg)) <= 20


def test_build_folder_and_filename_uses_templates():
    cfg = Config(
        folder_template="{albumartist} - {album}",
        filename_template="{tracknum:02d} - {title}",
        tracknum_padding=2,
    )
    t = _track(title="My Song", artists=["Artist X"], album="Their Album")
    folder, name = build_folder_and_filename(t, cfg, "flac")
    assert folder == "Artist X - Their Album"
    assert name == "03 - My Song.flac"


def test_build_folder_and_filename_playlist_uses_playlist_template():
    cfg = Config(create_playlist_folder=True)
    t = _track()
    folder, name = build_folder_and_filename(
        t, cfg, "flac",
        playlist_name="My Playlist", playlist_index=7, playlist_owner="me",
    )
    assert folder.startswith("Playlists/My Playlist")
    assert name == "07 - Artist - Title.flac"


def test_build_folder_and_filename_uses_extension():
    cfg = Config(filename_template="{title}")
    t = _track(title="My Song")
    _, name = build_folder_and_filename(t, cfg, "m4a")
    assert name == "My Song.m4a"


def test_build_folder_and_filename_handles_explicit():
    cfg = Config(filename_template="{title}{explicit_tag}")
    t_explicit = _track(title="E", explicit=True)
    t_clean = _track(title="E", explicit=False)
    _, name_e = build_folder_and_filename(t_explicit, cfg, "flac")
    _, name_c = build_folder_and_filename(t_clean, cfg, "flac")
    assert name_e == "E (Explicit).flac"
    assert name_c == "E.flac"