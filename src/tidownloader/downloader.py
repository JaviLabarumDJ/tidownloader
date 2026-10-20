"""Track-level download orchestration."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional

import requests
import tidalapi
import tidalapi.media

from .api import TrackInfo
from .config import Config, QUALITY_OPTIONS
from .manifest import (
    decrypt_segment,
    fetch_decryption_key,
    parse_manifest,
)
from .metadata import (
    download_cover,
    save_sidecar_cover,
    tag_file,
    target_path_for_track,
    write_m3u8,
)
from .templates import build_folder_and_filename

LOG = logging.getLogger("tidownloader.downloader")


# Map extension chosen by the user → actual file delivered by Tidal.
# All MP3 options download from Tidal's HIGH (AAC 320 kbps) and convert;
# M4A also uses HIGH but keeps the original; FLAC requests HI_RES and
# falls back to LOSSLESS if the track isn't available in hi-res.
SOURCE_FOR_QUALITY = {
    "mp3_128": "HIGH",
    "mp3_256": "HIGH",
    "mp3_320": "HIGH",
    "m4a":     "HIGH",
    "flac":    "HI_RES_LOSSLESS",
}
FALLBACK_FOR_QUALITY = {
    "flac":    "LOSSLESS",
}
MP3_BITRATE_FOR_QUALITY = {
    "mp3_128": 128,
    "mp3_256": 256,
    "mp3_320": 320,
}
TARGET_EXTENSION_FOR_QUALITY = {
    "mp3_128": "mp3",
    "mp3_256": "mp3",
    "mp3_320": "mp3",
    "m4a":     "m4a",
    "flac":    "flac",
}


def _convert_to_mp3(source: Path, target: Path, bitrate: int) -> Optional[Path]:
    """Re-encode ``source`` to MP3 at the given bitrate and write the
    result to ``target``. Returns ``target`` on success, ``None`` on
    failure. ``source`` and ``target`` must be different files.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        LOG.warning("ffmpeg not installed; cannot convert to MP3")
        return None
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-vn",
        "-codec:a", "libmp3lame",
        "-b:a", f"{bitrate}k",
        str(target),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=300)
    except subprocess.CalledProcessError as exc:
        LOG.warning("ffmpeg conversion failed: %s", exc)
        return None
    except subprocess.TimeoutExpired:
        LOG.warning("ffmpeg conversion timed out for %s", source)
        return None
    return target if target.exists() else None


def _maybe_postprocess(
    delivered_path: Path,
    target_path: Path,
    delivered_extension: str,
    quality_key: str,
) -> Path:
    """After Tidal delivers ``delivered_path`` (raw bytes from the
    stream), post-process it into ``target_path`` according to the
    user's quality choice:

    * MP3 options: convert the delivered M4A to MP3 at the requested
      bitrate. ``delivered_path`` is consumed (deleted on success).
    * M4A / FLAC: rename ``delivered_path`` to ``target_path``.
    """
    if quality_key not in MP3_BITRATE_FOR_QUALITY:
        # M4A or FLAC: just move the file to its final destination.
        if delivered_path != target_path:
            delivered_path.replace(target_path)
        return target_path

    delivered_ext = delivered_extension.lower().lstrip(".")
    if delivered_ext != "m4a":
        # Tidal delivered FLAC for a MP3 request — don't transcode.
        if delivered_path != target_path:
            delivered_path.replace(target_path)
        return target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    converted = _convert_to_mp3(
        delivered_path, target_path, MP3_BITRATE_FOR_QUALITY[quality_key]
    )
    if converted is None:
        # Fall back: leave the original in place but with the target name.
        try:
            if delivered_path.exists() and delivered_path != target_path:
                delivered_path.replace(target_path)
        except OSError:
            pass
        return target_path if target_path.exists() else delivered_path

    try:
        delivered_path.unlink()
    except OSError as exc:
        LOG.debug("Could not remove source %s: %s", delivered_path, exc)
    return converted


def _get_http_session(tidal_session: tidalapi.Session) -> requests.Session:
    return tidal_session.request_session


_STREAM_LOCK = threading.Lock()
_LAST_STREAM_TIME = 0.0
_ACCOUNT_RATE_LIMITED_UNTIL = 0.0


def _fetch_stream_unauth(
    session: tidalapi.Session,
    track_id: int,
    preferred_quality: str,
) -> Optional[tuple[tidalapi.media.Stream, tidalapi.media.StreamManifest]]:
    """Fallback: fetch playback stream info without Authorization header.

    When an account triggers Tidal's OAuth endpoint rate limit (429),
    Tidal continues to serve valid unencrypted AAC/MP4 streams (HIGH/LOW)
    for playback using just the public session ID.
    """
    qualities_to_try = [preferred_quality]
    if preferred_quality not in ("HIGH", "LOW"):
        qualities_to_try.extend(["HIGH", "LOW"])
    elif preferred_quality == "HIGH":
        qualities_to_try.append("LOW")
    elif preferred_quality == "LOW":
        qualities_to_try.append("HIGH")

    url = f"https://api.tidal.com/v1/tracks/{track_id}/playbackinfopostpaywall"
    session_id = getattr(session, "session_id", None)
    country_code = getattr(session, "country_code", None) or "ES"

    for q in qualities_to_try:
        params = {
            "sessionId": session_id,
            "countryCode": country_code,
            "playbackmode": "STREAM",
            "audioquality": q,
            "assetpresentation": "FULL",
        }
        try:
            resp = session.request_session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                stream = session.request.map_json(resp.json(), parse=tidalapi.media.Stream().parse)
                manifest = stream.get_stream_manifest()
                return stream, manifest
        except Exception as exc:
            LOG.debug("Unauth stream fetch error for track %s (%s): %s", track_id, q, exc)

    return None


def _fetch_stream_and_manifest(
    session: tidalapi.Session,
    track_id: int,
    preferred_quality: str,
    max_retries: int = 4,
) -> tuple[tidalapi.media.Stream, tidalapi.media.StreamManifest]:
    global _LAST_STREAM_TIME, _ACCOUNT_RATE_LIMITED_UNTIL

    # If the user account is in cooldown from a 429, bypass the failing
    # authenticated call and fetch unauthenticated stream directly.
    if time.time() < _ACCOUNT_RATE_LIMITED_UNTIL:
        with _STREAM_LOCK:
            elapsed = time.time() - _LAST_STREAM_TIME
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
            _LAST_STREAM_TIME = time.time()

        unauth_res = _fetch_stream_unauth(session, track_id, preferred_quality)
        if unauth_res is not None:
            return unauth_res

    for attempt in range(max_retries):
        try:
            with _STREAM_LOCK:
                elapsed = time.time() - _LAST_STREAM_TIME
                if elapsed < 1.0:
                    time.sleep(1.0 - elapsed)
                _LAST_STREAM_TIME = time.time()

                track_obj = session.track(track_id)
                if session.config.quality != preferred_quality:
                    session.config.quality = preferred_quality
                stream = track_obj.get_stream()
                manifest = stream.get_stream_manifest()
                return stream, manifest
        except Exception as exc:
            msg = str(exc)
            try:
                from tidalapi.exceptions import TooManyRequests, StreamNotAvailable
            except ImportError:
                TooManyRequests = tuple()
                StreamNotAvailable = tuple()

            is_429 = (
                (TooManyRequests and isinstance(exc, TooManyRequests))
                or getattr(getattr(exc, "response", None), "status_code", None) == 429
                or "429" in msg
                or "Too Many Requests" in msg
            )
            if is_429:
                _ACCOUNT_RATE_LIMITED_UNTIL = time.time() + 900.0  # 15 minutes cooldown
                LOG.warning(
                    "Tidal rate limit (429/TooManyRequests) on track %s; using unauthenticated stream fallback...",
                    track_id,
                )
                unauth_res = _fetch_stream_unauth(session, track_id, preferred_quality)
                if unauth_res is not None:
                    LOG.info("Unauthenticated stream fallback succeeded for track %s", track_id)
                    return unauth_res

                if attempt < max_retries - 1:
                    wait_sec = 15 * (attempt + 1)
                    LOG.warning(
                        "Fallback also rate limited; sleeping %ds (attempt %d/%d)...",
                        wait_sec, attempt + 1, max_retries,
                    )
                    time.sleep(wait_sec)
                    continue

            if (StreamNotAvailable and isinstance(exc, StreamNotAvailable)) or "404" in msg or "Not Found" in msg:
                raise

            is_transient = "timeout" in msg.lower() or "connection" in msg.lower()
            if is_transient and attempt < max_retries - 1:
                wait_sec = 2 ** (attempt + 1)
                LOG.warning(
                    "Track %s stream fetch attempt %d failed (%s); retrying in %ds...",
                    track_id, attempt + 1, exc, wait_sec,
                )
                time.sleep(wait_sec)
                continue
            raise


def _try_quality(
    session: tidalapi.Session,
    track_id: int,
    tidal_quality: str,
) -> tuple[tidalapi.media.Stream, tidalapi.media.StreamManifest]:
    try:
        return _fetch_stream_and_manifest(session, track_id, tidal_quality)
    except Exception as exc:
        LOG.debug("Quality %s unavailable for track %s: %s",
                  tidal_quality, track_id, exc)
        raise


def _fetch_lyrics(session: tidalapi.Session, track_id: int) -> tuple[Optional[str], Optional[str]]:
    """Return (plain_text_lyrics, synced_lyrics_subtitles)."""
    try:
        track_obj = session.track(track_id)
        lyrics = track_obj.lyrics()
        if not lyrics:
            return None, None
        plain = lyrics.text if lyrics.text else None
        synced = getattr(lyrics, "subtitles", None)
        return plain, synced
    except Exception as exc:
        LOG.debug("Lyrics not available for %s: %s", track_id, exc)
        return None, None


def _search_alternative_track(session: tidalapi.Session, track: TrackInfo) -> Optional[int]:
    """Search Tidal for an alternative available track when the original is 404 or removed."""
    artist_name = track.artists[0] if track.artists else ""
    query = f"{artist_name} {track.title}".strip()
    if not query:
        return None
    try:
        res = session.search(query, models=[tidalapi.media.Track], limit=5)
        tracks = res.get("tracks", []) if isinstance(res, dict) else getattr(res, "tracks", [])
        norm_title = re.sub(r"[^a-z0-9]", "", track.title.lower())
        for cand in tracks:
            if cand.id == track.track_id or not cand.available:
                continue
            cand_title = re.sub(r"[^a-z0-9]", "", cand.title.lower())
            if cand_title == norm_title or norm_title in cand_title:
                return cand.id
    except Exception as exc:
        LOG.debug("Search for alternative track failed for %s: %s", track.title, exc)
    return None


def _fetch_upc(session: tidalapi.Session, album_id: int) -> str:
    if not album_id:
        return ""
    try:
        album = session.album(album_id)
        return getattr(album, "upc", "") or ""
    except Exception:
        return ""


def _download_segments(
    http: requests.Session,
    urls: list[str],
    on_segment: Optional[callable] = None,
) -> list[bytes]:
    payloads: list[Optional[bytes]] = [None] * len(urls)
    lock = threading.Lock()
    completed = 0

    def _fetch_one(idx: int, url: str) -> None:
        nonlocal completed
        retries = 3
        for attempt in range(retries):
            try:
                response = http.get(url, stream=True, timeout=60)
                if response.status_code == 429 and attempt < retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                response.raise_for_status()
                buf = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        buf.extend(chunk)
                payloads[idx] = bytes(buf)
                break
            except Exception as exc:
                if attempt == retries - 1:
                    raise
                time.sleep(1 + attempt)
        with lock:
            completed += 1
            if on_segment:
                on_segment(completed)

    workers = min(8, max(1, len(urls)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_one, i, u) for i, u in enumerate(urls)]
        for f in futures:
            f.result()
    return payloads  # type: ignore[return-value]


def download_track(
    session: tidalapi.Session,
    track: TrackInfo,
    cfg: Config,
    on_progress: Optional[callable] = None,
    playlist_name: str = "",
    playlist_index: Optional[int] = None,
    playlist_owner: str = "",
) -> Optional[Path]:
    """Download one track according to ``cfg``.

    Returns the final file path, or ``None`` if the track was skipped
    or the download failed (e.g. FLAC requested but no lossless stream
    is available).
    """
    quality_key = cfg.quality
    primary_quality = SOURCE_FOR_QUALITY[quality_key]
    fallback_quality = FALLBACK_FOR_QUALITY.get(quality_key)
    target_extension = TARGET_EXTENSION_FOR_QUALITY[quality_key]

    # Early check for skip_existing BEFORE making any network call to Tidal
    target_early, _ = target_path_for_track(
        track,
        cfg,
        extension=target_extension,
        playlist_name=playlist_name,
        playlist_index=playlist_index,
        playlist_owner=playlist_owner,
    )
    if cfg.skip_existing and target_early.exists() and not cfg.overwrite_existing:
        LOG.info("Skipping existing file: %s", target_early)
        return target_early

    session.config.quality = primary_quality

    # First attempt at the requested quality.
    stream_obj = None
    manifest = None

    try:
        stream_obj, manifest = _fetch_stream_and_manifest(
            session, track.track_id, primary_quality
        )
    except Exception as primary_exc:
        LOG.info("%s: %s unavailable (%s)", track.title, primary_quality, primary_exc)
        if fallback_quality:
            try:
                stream_obj, manifest = _fetch_stream_and_manifest(
                    session, track.track_id, fallback_quality
                )
            except Exception as fallback_exc:
                LOG.warning(
                    "%s: no stream available at %s or %s (%s / %s)",
                    track.title, primary_quality, fallback_quality,
                    primary_exc, fallback_exc,
                )

    used_track_id: Optional[int] = None
    if (stream_obj is None or manifest is None) and cfg.fallback_search_missing:
        alt_track_id = _search_alternative_track(session, track)
        if alt_track_id:
            LOG.info("Searching fallback stream for %s using alternative track ID %s...", track.title, alt_track_id)
            try:
                stream_obj, manifest = _fetch_stream_and_manifest(
                    session, alt_track_id, primary_quality
                )
                used_track_id = alt_track_id
            except Exception:
                if fallback_quality:
                    try:
                        stream_obj, manifest = _fetch_stream_and_manifest(
                            session, alt_track_id, fallback_quality
                        )
                        used_track_id = alt_track_id
                    except Exception:
                        pass

    if stream_obj is None or manifest is None:
        LOG.warning("%s: no stream available", track.title)
        return None

    try:
        info = parse_manifest(stream_obj, manifest)
    except Exception as exc:
        LOG.warning("Skipping %s: manifest parse failed: %s", track.title, exc)
        return None

    cipher = info.cipher_scheme
    bit_depth = int(info.sample_rate or 0)
    sample_rate = int(info.sample_rate or 0)
    quality_label = manifest.codecs or primary_quality
    delivered_extension = "flac" if "flac" in info.codecs.lower() else info.file_extension

    key: Optional[bytes] = None
    if info.kid:
        try:
            key = fetch_decryption_key(session, info.kid)
        except Exception as exc:
            LOG.warning("Could not fetch decryption key for %s: %s", track.title, exc)
            return None

    # Resolve final target path (with bit depth / quality label if configured)
    target, folder_rel = target_path_for_track(
        track,
        cfg,
        extension=target_extension,
        quality_label=quality_label,
        bit_depth=bit_depth,
        sample_rate=sample_rate,
        playlist_name=playlist_name,
        playlist_index=playlist_index,
        playlist_owner=playlist_owner,
    )

    if cfg.skip_existing and target.exists() and not cfg.overwrite_existing:
        LOG.info("Skipping existing file: %s", target)
        return target

    # Write the delivered audio to a temp file using the *delivered*
    # extension. _maybe_postprocess will rename/convert it to the
    # user-facing target afterwards.
    target.parent.mkdir(parents=True, exist_ok=True)
    delivered_extension_clean = delivered_extension.lstrip(".")
    delivered_path = target.with_suffix("." + delivered_extension_clean)
    if delivered_path == target:
        # Unlikely: user wants the same extension Tidal delivers.
        delivered_path = target.with_suffix(target.suffix + ".delivered")

    segments_to_fetch: list[str] = []
    if info.init_url:
        segments_to_fetch.append(info.init_url)
    segments_to_fetch.extend(info.segment_urls)

    if not segments_to_fetch:
        LOG.warning("No segments found for %s", track.title)
        return None

    total = len(segments_to_fetch)
    http = _get_http_session(session)

    def _notify(c: int) -> None:
        if on_progress:
            on_progress(c, total)

    raw_segments = _download_segments(http, segments_to_fetch, _notify)

    out = bytearray()
    if raw_segments:
        out.extend(raw_segments[0])
    for idx, segment in enumerate(raw_segments[1:], start=1):
        if key is None:
            out.extend(segment)
        else:
            out.extend(decrypt_segment(key, idx, cipher, segment))

    tmp = delivered_path.with_suffix(delivered_path.suffix + ".part")
    tmp.write_bytes(bytes(out))
    tmp.replace(delivered_path)

    cover = (
        download_cover(http, track.cover_id, cfg)
        if (cfg.embed_cover or cfg.save_cover_in_folder)
        else None
    )
    lyrics_plain, lyrics_synced = (None, None)
    if cfg.embed_lyrics or cfg.save_lrc_file:
        lyrics_plain, lyrics_synced = _fetch_lyrics(session, used_track_id or track.track_id)

    upc = _fetch_upc(session, track.album_id) if cfg.embed_upc else ""

    # Tag the *final* path (post-conversion), so the tags match the
    # actual file format the user asked for. If we tag the M4A source
    # first and then convert, the ID3 tags would survive (libmp3lame
    # copies them) but the FLAC/M4A native tags would be lost.
    final = _maybe_postprocess(delivered_path, target, delivered_extension, quality_key)

    try:
        tag_file(final, track, cover, target_extension, lyrics=lyrics_plain if cfg.embed_lyrics else None, upc=upc)
    except Exception as exc:
        LOG.warning("Failed to tag %s: %s", final, exc)

    if cfg.save_lrc_file and (lyrics_synced or lyrics_plain):
        try:
            lrc_path = final.with_suffix(".lrc")
            lrc_path.write_text(lyrics_synced or lyrics_plain, encoding="utf-8")
            LOG.debug("Saved .lrc lyrics: %s", lrc_path)
        except Exception as exc:
            LOG.warning("Could not save .lrc lyrics file: %s", exc)

    if cover and cfg.save_cover_in_folder and folder_rel:
        try:
            save_sidecar_cover(final.parent, cover, cfg.cover_filename, cfg)
        except Exception as exc:
            LOG.debug("Sidecar cover failed: %s", exc)

    return final


def download_tracks(
    session: tidalapi.Session,
    tracks: list[TrackInfo],
    cfg: Config,
    on_progress: Optional[callable] = None,
    playlist_name: str = "",
    playlist_owner: str = "",
) -> list[tuple[TrackInfo, Optional[Path]]]:
    """Download a list of tracks with the configured concurrency."""
    if not tracks:
        return []

    out_dir = Path(cfg.download_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(cfg.concurrent_downloads, len(tracks)))
    results: list[Optional[Path]] = [None] * len(tracks)
    lock = threading.Lock()
    completed = 0
    total = len(tracks)

    def _one(idx: int, track: TrackInfo) -> None:
        nonlocal completed
        path = download_track(
            session,
            track,
            cfg,
            playlist_name=playlist_name,
            playlist_index=(idx + 1) if playlist_name else None,
            playlist_owner=playlist_owner,
        )
        with lock:
            results[idx] = path
            completed += 1
            if on_progress:
                on_progress(completed, total, track)

    if workers == 1:
        for i, t in enumerate(tracks):
            _one(i, t)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_one, i, t) for i, t in enumerate(tracks)]
            for f in futures:
                f.result()

    if cfg.create_m3u8 and playlist_name:
        entries: list[tuple[str, str]] = []
        for (track, path) in zip(tracks, results):
            if path is None:
                continue
            try:
                rel = path.parent.relative_to(out_dir).as_posix()
            except ValueError:
                rel = ""
            entries.append((rel, path.name))
        try:
            write_m3u8(out_dir, "", entries, cfg, playlist_name)
        except Exception as exc:
            LOG.warning("M3U8 write failed: %s", exc)

    return list(zip(tracks, results))