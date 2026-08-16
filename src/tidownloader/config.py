"""User-configurable settings.

The :class:`Config` dataclass is the single source of truth. Quality is
a single user-facing enum (``mp3_128`` / ``mp3_256`` / ``mp3_320`` /
``m4a`` / ``flac``); the rest of the config deals with filenames, tags,
concurrency, etc.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict

LOG = logging.getLogger("tidownloader.config")


# --------------------------------------------------------------------------- #
# Quality options — the *only* place the user has to choose.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class QualityOption:
    key: str                 # config value, e.g. "mp3_320"
    label: str               # UI label, e.g. "High (MP3 320 kbps)"
    description: str         # help text shown under the dropdown
    tidal_quality: str       # API value: LOW | HIGH | LOSSLESS | HI_RES_LOSSLESS
    fallback: str | None     # next API quality to try if the first fails
    file_extension: str      # "mp3" | "m4a" | "flac"
    container_mime: str      # used for tagging


QUALITY_OPTIONS: Dict[str, QualityOption] = {
    "mp3_128": QualityOption(
        key="mp3_128",
        label="Low (MP3 128 kbps)",
        description="Smallest files. Source: Tidal HIGH (AAC 320 kbps), re-encoded.",
        tidal_quality="HIGH",
        fallback=None,
        file_extension="mp3",
        container_mime="audio/mpeg",
    ),
    "mp3_256": QualityOption(
        key="mp3_256",
        label="Medium (MP3 256 kbps)",
        description="Good balance between size and quality.",
        tidal_quality="HIGH",
        fallback=None,
        file_extension="mp3",
        container_mime="audio/mpeg",
    ),
    "mp3_320": QualityOption(
        key="mp3_320",
        label="High (MP3 320 kbps) — recommended",
        description="Best MP3 quality. Default.",
        tidal_quality="HIGH",
        fallback=None,
        file_extension="mp3",
        container_mime="audio/mpeg",
    ),
    "m4a": QualityOption(
        key="m4a",
        label="M4A (AAC 320 kbps)",
        description="Tidal's native lossy format, no re-encoding.",
        tidal_quality="HIGH",
        fallback=None,
        file_extension="m4a",
        container_mime="audio/mp4",
    ),
    "flac": QualityOption(
        key="flac",
        label="FLAC (Lossless)",
        description="Hi-Res when available, falls back to CD-quality lossless.",
        tidal_quality="HI_RES_LOSSLESS",
        fallback="LOSSLESS",
        file_extension="flac",
        container_mime="audio/flac",
    ),
}

# Order shown in the UI.
QUALITY_ORDER = ["mp3_128", "mp3_256", "mp3_320", "m4a", "flac"]
DEFAULT_QUALITY = "mp3_320"

# Legacy UI keys that older config.json files may still contain; mapped
# to their modern equivalent so existing installs keep working.
LEGACY_QUALITY_MAP = {
    "low": "mp3_128",
    "medium": "mp3_256",
    "high": "mp3_320",
    "lossless": "flac",
    "hi_res": "flac",
    "max": "mp3_320",  # was HI_RES_LOSSLESS, but for most users the old
                        # default was effectively "lossy when not available"
                        # so we keep MP3 320 as the safer default
}


def resolve_quality_key(value: str) -> str:
    """Normalise a quality string from anywhere (UI, URL, config file)
    to a key in :data:`QUALITY_OPTIONS`. Falls back to the default."""
    if not value:
        return DEFAULT_QUALITY
    key = value.lower()
    if key in QUALITY_OPTIONS:
        return key
    if key in LEGACY_QUALITY_MAP:
        return LEGACY_QUALITY_MAP[key]
    return DEFAULT_QUALITY


COVER_SIZES = [320, 640, 1280, 1920, 3000]


# --------------------------------------------------------------------------- #
# Config dataclass
# --------------------------------------------------------------------------- #


@dataclass
class Config:
    # ---------- Storage ----------
    download_path: str = "/downloads"

    # ---------- Quality (single setting, the rest is automatic) ----------
    quality: str = DEFAULT_QUALITY

    # ---------- Folder / filename templates ----------
    folder_template: str = "{albumartist} - {album}"
    filename_template: str = "{tracknum:02d} - {title}"
    playlist_filename_template: str = "{playlistnum:02d} - {artist} - {title}"
    playlist_folder_template: str = "Playlists/{playlist}"
    compilation_folder_template: str = "Compilations/{album}"
    create_playlist_folder: bool = True
    create_compilation_folder: bool = True

    # ---------- Various Artists ----------
    various_artists_name: str = "Various Artists"
    detect_compilations: bool = True

    # ---------- Number padding ----------
    tracknum_padding: int = 2
    discnum_padding: int = 2

    # ---------- Files / artwork ----------
    save_cover_in_folder: bool = True
    cover_filename: str = "cover.jpg"
    embed_cover: bool = True
    cover_size: int = 1280

    # ---------- Tags ----------
    embed_lyrics: bool = True
    embed_isrc: bool = True
    embed_upc: bool = True

    # ---------- Playlist file ----------
    create_m3u8: bool = False
    m3u8_filename: str = "{playlist}.m3u8"

    # ---------- Filename safety ----------
    sanitize_filenames: bool = True
    max_filename_length: int = 200
    replace_spaces: bool = False
    replacement_char: str = "_"

    # ---------- Concurrency ----------
    concurrent_downloads: int = 1
    max_workers: int = 4

    # ---------- Behaviour ----------
    skip_existing: bool = True
    overwrite_existing: bool = False
    remove_finished: bool = False
    retry_on_error: int = 2

    # ---------- Search / fallback ----------
    fallback_language: str = "en"
    log_searched: bool = False

    # ---------- Metadata fields ----------
    artist_separator: str = ", "

    # ------------------------------------------------------------------ #
    # Validation & (de)serialisation
    # ------------------------------------------------------------------ #

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        # Strip unknown fields so a stale config doesn't crash us.
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        cfg = cls(**clean)
        cfg._validate()
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _validate(self) -> None:
        # Quality: normalise via the public helper so legacy strings
        # ("max", "hi_res", "lossless"…) are mapped to a valid key.
        self.quality = resolve_quality_key(self.quality)
        if self.cover_size not in COVER_SIZES:
            self.cover_size = 1280
        self.tracknum_padding = max(1, min(self.tracknum_padding, 6))
        self.discnum_padding = max(1, min(self.discnum_padding, 6))
        self.concurrent_downloads = max(1, min(self.concurrent_downloads, self.max_workers))
        self.max_filename_length = max(20, min(self.max_filename_length, 500))
        self.retry_on_error = max(0, min(self.retry_on_error, 10))

    # ------------------------------------------------------------------ #
    # Convenience: the resolved QualityOption for the current config.
    # ------------------------------------------------------------------ #

    @property
    def quality_option(self) -> QualityOption:
        return QUALITY_OPTIONS[self.quality]


class ConfigStore:
    """Persist a Config to a JSON file."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except Exception as exc:
                LOG.warning("Could not read %s: %s", self.path, exc)
                self._data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False))

    def get(self) -> Config:
        return Config.from_dict(self._data)

    def update(self, data: Dict[str, Any]) -> Config:
        known = {f.name for f in fields(Config)}
        for k, v in data.items():
            if k in known:
                self._data[k] = v
        cfg = Config.from_dict(self._data)
        self._data = cfg.to_dict()
        self._save()
        return cfg

    def reset(self) -> Config:
        self._data = {}
        cfg = Config()
        self._data = cfg.to_dict()
        self._save()
        return cfg


# --------------------------------------------------------------------------- #
# Settings schema for the UI. Order here = order in the Settings panel.
# --------------------------------------------------------------------------- #

OPTION_SCHEMA = [
    {"key": "download_path", "label": "Download folder", "type": "path",
     "help": "Where files are saved. Inside Docker this must live in a bind-mounted volume (default: /downloads, mapped to ./downloads on the host)."},
    {"key": "quality", "label": "Audio quality", "type": "select",
     "options": [(k, QUALITY_OPTIONS[k].label) for k in QUALITY_ORDER],
     "help": "MP3 options re-encode Tidal's AAC 320 kbps stream via ffmpeg. M4A keeps Tidal's native AAC. FLAC is lossless."},

    {"key": "save_cover_in_folder", "label": "Save cover.jpg next to the tracks", "type": "bool",
     "section": "Cover art"},
    {"key": "cover_filename", "label": "Cover filename", "type": "text"},
    {"key": "embed_cover", "label": "Embed cover in tags", "type": "bool"},
    {"key": "cover_size", "label": "Cover size (pixels)", "type": "select",
     "options": COVER_SIZES},

    {"key": "embed_lyrics", "label": "Embed lyrics", "type": "bool",
     "section": "Tags"},
    {"key": "embed_isrc", "label": "Embed ISRC", "type": "bool"},
    {"key": "embed_upc", "label": "Embed UPC", "type": "bool"},

    {"key": "folder_template", "label": "Album folder", "type": "text",
     "section": "Folder & filenames",
     "help": "Variables: {albumartist} {album} {year} {quality}"},
    {"key": "filename_template", "label": "Track filename", "type": "text",
     "help": "Variables: {tracknum} {title} {artist} {album}"},
    {"key": "playlist_folder_template", "label": "Playlist folder", "type": "text"},
    {"key": "playlist_filename_template", "label": "Playlist track filename", "type": "text"},
    {"key": "compilation_folder_template", "label": "Compilation folder", "type": "text"},
    {"key": "create_playlist_folder", "label": "Put playlists in their own folder", "type": "bool"},
    {"key": "create_compilation_folder", "label": "Put compilations in their own folder", "type": "bool"},
    {"key": "detect_compilations", "label": "Detect compilations", "type": "bool"},
    {"key": "various_artists_name", "label": "Various Artists name", "type": "text"},
    {"key": "tracknum_padding", "label": "Track number padding", "type": "int",
     "help": "2 → 01, 02, 03…"},
    {"key": "discnum_padding", "label": "Disc number padding", "type": "int"},
    {"key": "sanitize_filenames", "label": "Strip illegal characters from filenames", "type": "bool"},
    {"key": "replace_spaces", "label": "Replace spaces with underscores", "type": "bool"},
    {"key": "replacement_char", "label": "Replacement character", "type": "text"},
    {"key": "max_filename_length", "label": "Max filename length", "type": "int"},
    {"key": "artist_separator", "label": "Artist separator", "type": "text"},

    {"key": "create_m3u8", "label": "Create .m3u8 for playlists", "type": "bool",
     "section": "Playlist file"},
    {"key": "m3u8_filename", "label": ".m3u8 filename", "type": "text"},

    {"key": "concurrent_downloads", "label": "Tracks downloaded in parallel", "type": "int",
     "section": "Speed",
     "help": "1 = serial, 2-4 = parallel. Tidal rate-limits above ~4."},
    {"key": "max_workers", "label": "Worker pool cap", "type": "int"},

    {"key": "skip_existing", "label": "Skip tracks already on disk", "type": "bool",
     "section": "Behaviour"},
    {"key": "overwrite_existing", "label": "Overwrite existing files", "type": "bool"},
    {"key": "remove_finished", "label": "Remove finished jobs from the queue", "type": "bool"},
    {"key": "retry_on_error", "label": "Retries on transient errors", "type": "int"},

    {"key": "fallback_language", "label": "Fallback metadata language", "type": "text",
     "section": "Search"},
    {"key": "log_searched", "label": "Verbose search logging", "type": "bool"},
]