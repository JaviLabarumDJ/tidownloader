"""Render filename / folder templates.

Templates use Python's :func:`str.format` syntax, e.g.
``"{tracknum:02d} - {artist} - {title}"``. Missing keys become empty
strings so a single template works for any track.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence

from .api import TrackInfo
from .config import Config

# --------------------------------------------------------------------------- #
# Compiled regex for the {var[:spec]} placeholder.
# --------------------------------------------------------------------------- #

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][\w]*)(?::([^}]*))?\}")


@dataclass
class RenderContext:
    """Variables exposed to a template."""

    # Track
    title: str = ""
    tracknum: str = ""
    discnum: str = ""
    isrc: str = ""
    upc: str = ""
    explicit_tag: str = ""

    # Artist / album
    artist: str = ""
    artists: str = ""
    albumartist: str = ""
    albumartists: str = ""

    # Album
    album: str = ""
    year: str = ""
    date: str = ""
    album_id: str = ""

    # Quality (filled at render-time from the manifest)
    bitdepth: str = ""
    samplerate: str = ""
    bitrate: str = ""
    quality: str = ""
    ext: str = ""

    # Playlist
    playlist: str = ""
    playlistnum: str = ""
    playlistowner: str = ""


_SAFE_CHARS = re.compile(r"[^A-Za-z0-9 _\-\.\(\)\[\]\u00C0-\uFFFF]")
# Characters that are unsafe inside a *single* path segment. Slashes are
# unsafe at the segment level (they split segments) but legitimate as
# path separators inside a folder template — those are handled separately.
_SEGMENT_UNSAFE_CHARS = re.compile(r"[/\\<>:\"|?*\x00-\x1F]")


def sanitize(name: str, cfg: Config, *, allow_slashes: bool = False) -> str:
    if not cfg.sanitize_filenames:
        return name
    if allow_slashes:
        # Sanitize each path segment independently so folder templates
        # like "Playlists/{playlist}" keep their structure.
        segments = name.split("/") if "/" in name else [name]
        segments = [sanitize(s, cfg, allow_slashes=False) for s in segments]
        out = "/".join(s for s in segments if s)
    else:
        out = _SEGMENT_UNSAFE_CHARS.sub(cfg.replacement_char, name)
        out = _SAFE_CHARS.sub(cfg.replacement_char, out)
        if cfg.replace_spaces:
            out = out.replace(" ", cfg.replacement_char)
        out = out.strip(" ._")
        if len(out) > cfg.max_filename_length:
            head, _, tail = out.rpartition(cfg.replacement_char)
            keep_tail = cfg.max_filename_length - len(head) - 1
            if keep_tail > 20 and tail:
                out = head + cfg.replacement_char + tail[-keep_tail:]
            else:
                out = out[: cfg.max_filename_length]
        out = out or "_"
    return out


def _track_to_context(
    track: TrackInfo,
    cfg: Config,
    extension: str,
    quality_label: str = "",
    bit_depth: Optional[int] = None,
    sample_rate: Optional[int] = None,
    playlist_name: str = "",
    playlist_index: Optional[int] = None,
    playlist_owner: str = "",
    upc: str = "",
) -> RenderContext:
    artists = track.artists or [cfg.various_artists_name]
    artist = artists[0] if artists else cfg.various_artists_name
    is_compilation = cfg.detect_compilations and _looks_like_compilation(track)

    albumartist = (
        cfg.various_artists_name if is_compilation else artist
    )

    tracknum = (
        str(track.track_number or 0).zfill(cfg.tracknum_padding)
        if track.track_number is not None
        else ""
    )
    discnum = (
        str(track.disc_number or 0).zfill(cfg.discnum_padding)
        if track.disc_number is not None
        else ""
    )
    year = ""
    date = track.release_date or ""
    if date and len(date) >= 4 and date[:4].isdigit():
        year = date[:4]

    explicit_tag = " (Explicit)" if track.explicit else ""

    playlist_clean = sanitize(playlist_name, cfg, allow_slashes=False) if playlist_name else ""

    return RenderContext(
        title=track.title,
        tracknum=tracknum,
        discnum=discnum,
        isrc=track.isrc or "",
        upc=upc,
        explicit_tag=explicit_tag,
        artist=artist,
        artists=cfg.artist_separator.join(artists),
        albumartist=albumartist,
        albumartists=cfg.artist_separator.join(artists),
        album=track.album,
        year=year,
        date=date,
        album_id=str(track.album_id),
        bitdepth=str(bit_depth or ""),
        samplerate=str(sample_rate or ""),
        bitrate="",
        quality=quality_label,
        ext=extension,
        playlist=playlist_clean,
        playlistnum=(
            str(playlist_index).zfill(cfg.tracknum_padding)
            if playlist_index
            else ""
        ),
        playlistowner=playlist_owner,
    )


def _looks_like_compilation(track: TrackInfo) -> bool:
    """Tidal's API doesn't expose a clean compilation flag, so we
    infer it: if the album has many distinct primary artists, treat it
    as a compilation. The caller may also override via metadata."""
    return False  # hook for future enrichment


def render(template: str, ctx: RenderContext) -> str:
    """Render a template like ``"{tracknum:02d} - {title}"``.

    Unknown placeholders become empty strings rather than raising so
    that templates work on partial data.
    """

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        spec = match.group(2)
        value = getattr(ctx, key, "")
        if spec:
            try:
                # Allow numeric conversions like {tracknum:02d}; values
                # are strings so pad/zfill work transparently.
                if spec.endswith("d"):
                    width = int(spec[:-1])
                    value = str(int(value) if value else 0).zfill(width)
                elif spec.endswith("s"):
                    width = int(spec[:-1])
                    value = (value or "").ljust(width)[:width]
                elif spec.endswith(">") or spec.endswith("<"):
                    width = int(spec[:-1])
                    align_char = spec[-1]
                    if align_char == ">":
                        value = (value or "").rjust(width)
                    else:
                        value = (value or "").ljust(width)
            except (ValueError, TypeError):
                pass
        return str(value)

    return _PLACEHOLDER_RE.sub(repl, template)


# --------------------------------------------------------------------------- #
# Top-level helpers used by the downloader.
# --------------------------------------------------------------------------- #


def build_folder_and_filename(
    track: TrackInfo,
    cfg: Config,
    extension: str,
    quality_label: str = "",
    bit_depth: Optional[int] = None,
    sample_rate: Optional[int] = None,
    playlist_name: str = "",
    playlist_index: Optional[int] = None,
    playlist_owner: str = "",
    upc: str = "",
) -> tuple[str, str]:
    """Return ``(folder_relative_to_output, filename)``.

    The folder is relative to ``cfg.download_path``. Empty string means
    the file goes directly in the output root. Trailing slashes are
    stripped.
    """
    ctx = _track_to_context(
        track,
        cfg,
        extension=extension,
        quality_label=quality_label,
        bit_depth=bit_depth,
        sample_rate=sample_rate,
        playlist_name=playlist_name,
        playlist_index=playlist_index,
        playlist_owner=playlist_owner,
        upc=upc,
    )

    is_playlist = bool(playlist_name) and cfg.create_playlist_folder
    is_compilation = (
        cfg.detect_compilations
        and _looks_like_compilation(track)
        and cfg.create_compilation_folder
        and not is_playlist
    )

    if is_playlist:
        folder_tpl = cfg.playlist_folder_template
        filename_tpl = cfg.playlist_filename_template
    elif is_compilation:
        folder_tpl = cfg.compilation_folder_template
        filename_tpl = cfg.filename_template
    else:
        folder_tpl = cfg.folder_template
        filename_tpl = cfg.filename_template

    folder_raw = render(folder_tpl, ctx).strip("/\\ ")
    folder = sanitize(folder_raw, cfg, allow_slashes=True) if folder_raw else ""

    filename_raw = render(filename_tpl, ctx).strip()
    filename = sanitize(filename_raw, cfg, allow_slashes=False)
    if not filename.endswith("." + extension):
        filename = filename + "." + extension

    return folder, filename