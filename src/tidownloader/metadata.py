"""Metadata helpers: template-based paths, cover art, lyrics, M3U8, tagging."""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Iterable, Optional

import requests
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    ID3,
    ID3NoHeaderError,
    TALB,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TCON,
    TRCK,
    TPOS,
    USLT,
    APIC,
)
from mutagen.mp4 import MP4, MP4Cover

from .api import TrackInfo
from .config import Config
from .templates import build_folder_and_filename, sanitize

LOG = logging.getLogger("tidownloader.metadata")


def _download_cover(
    session: requests.Session,
    cover_id: Optional[str],
    size: int = 1280,
) -> Optional[bytes]:
    if not cover_id:
        return None
    url = f"https://resources.tidal.com/images/{cover_id.replace('-', '/')}/{size}x{size}.jpg"
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception as exc:
        LOG.warning("Failed to download cover art %s: %s", cover_id, exc)
        return None


def fetch_cover_url(cover_id: str, size: int) -> str:
    return f"https://resources.tidal.com/images/{cover_id.replace('-', '/')}/{size}x{size}.jpg"


def download_cover(session: requests.Session, cover_id: str, cfg: Config) -> Optional[bytes]:
    return _download_cover(session, cover_id, cfg.cover_size)


def _tag_flac(
    path: Path,
    track: TrackInfo,
    cover: Optional[bytes],
    lyrics: Optional[str],
    upc: str = "",
) -> None:
    audio = FLAC(path)
    audio["title"] = track.title
    audio["artist"] = track.artists
    audio["album"] = track.album
    audio["albumartist"] = track.artists[0] if track.artists else ""
    audio["tracknumber"] = str(track.track_number or 0)
    audio["discnumber"] = str(track.disc_number or 0)
    if track.isrc:
        audio["isrc"] = track.isrc
    if upc:
        audio["upc"] = upc
    if track.release_date:
        audio["date"] = track.release_date
    if cover:
        pic = Picture()
        pic.data = cover
        pic.mime = "image/jpeg"
        pic.type = 3
        audio.add_picture(pic)
    if lyrics:
        audio["lyrics"] = lyrics
    audio.save()


def _tag_m4a(
    path: Path,
    track: TrackInfo,
    cover: Optional[bytes],
    lyrics: Optional[str],
    upc: str = "",
) -> None:
    audio = MP4(path)
    audio["\xa9nam"] = track.title
    audio["\xa9ART"] = track.artists
    audio["\xa9alb"] = track.album
    audio["aART"] = track.artists[0] if track.artists else ""
    audio["trkn"] = [(track.track_number or 0, 0)]
    audio["disk"] = [(track.disc_number or 0, 0)]
    if track.isrc:
        audio["----:com.apple.iTunes:ISRC"] = track.isrc.encode("utf-8")
    if upc:
        audio["----:com.apple.iTunes:UPC"] = upc.encode("utf-8")
    if track.release_date:
        audio["\xa9day"] = track.release_date
    if cover:
        audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    if lyrics:
        audio["\xa9lyr"] = lyrics
    audio.save()


def _tag_mp3(
    path: Path,
    track: TrackInfo,
    cover: Optional[bytes],
    lyrics: Optional[str],
    upc: str = "",
) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=track.title))
    if track.artists:
        tags.add(TPE1(encoding=3, text=track.artists))
        tags.add(TPE2(encoding=3, text=track.artists[0]))
    tags.add(TALB(encoding=3, text=track.album))
    if track.track_number:
        tags.add(TRCK(encoding=3, text=str(track.track_number)))
    if track.disc_number:
        tags.add(TPOS(encoding=3, text=str(track.disc_number)))
    if track.release_date:
        tags.add(TDRC(encoding=3, text=track.release_date))
    if track.isrc:
        tags.add(TCON(encoding=3, text=track.isrc))
    if cover:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="cover", data=cover))
    if lyrics:
        tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))
    tags.save(path)


def tag_file(
    path: Path,
    track: TrackInfo,
    cover: Optional[bytes],
    extension: str,
    lyrics: Optional[str] = None,
    upc: str = "",
) -> None:
    ext = extension.lower().lstrip(".")
    if ext == "flac":
        _tag_flac(path, track, cover, lyrics, upc)
    elif ext in ("m4a", "mp4"):
        _tag_m4a(path, track, cover, lyrics, upc)
    elif ext == "mp3":
        _tag_mp3(path, track, cover, lyrics, upc)
    else:
        LOG.debug("No tagger for extension %s; skipping metadata", ext)


def save_sidecar_cover(
    folder: Path,
    cover: bytes,
    filename: str,
    cfg: Config,
) -> Optional[Path]:
    if not cfg.save_cover_in_folder:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize(filename, cfg) or "cover.jpg"
    target = folder / safe_name
    target.write_bytes(cover)
    return target


# --------------------------------------------------------------------------- #
# M3U8 playlist writer
# --------------------------------------------------------------------------- #


def write_m3u8(
    out_dir: Path,
    folder_rel: str,
    entries: list[tuple[str, str]],
    cfg: Config,
    playlist_name: str,
) -> Optional[Path]:
    """Write an .m3u8 playlist listing the downloaded tracks.

    ``entries`` is a list of (folder_relative_to_outdir, filename).
    """
    if not cfg.create_m3u8 or not entries:
        return None

    # Build the m3u8 filename from its template.
    from .templates import RenderContext, render

    ctx = RenderContext(playlist=playlist_name, ext="m3u8")
    fname = sanitize(render(cfg.m3u8_filename, ctx), cfg)
    if not fname.endswith(".m3u8"):
        fname += ".m3u8"

    target = (out_dir / fname) if not folder_rel else (out_dir / folder_rel / fname)
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = ["#EXTM3U"]
    for subfolder, filename in entries:
        rel = (Path(subfolder) / filename).as_posix() if subfolder else filename
        lines.append(rel)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


# --------------------------------------------------------------------------- #
# Skip-existing
# --------------------------------------------------------------------------- #


def target_path_for_track(
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
) -> tuple[Path, str]:
    """Return ``(absolute_path, folder_relative_to_output)``.

    Raises nothing; uses the configured templates.
    """
    folder_rel, filename = build_folder_and_filename(
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
    out = Path(cfg.download_path)
    base = out / folder_rel if folder_rel else out
    return base / filename, folder_rel