"""Tidal URL resolution and metadata helpers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

import tidalapi

LOG = logging.getLogger("tidownloader.api")

URL_PATTERNS = [
    ("playlist", re.compile(r"/(?:playlist|browse/playlist)/([0-9a-f-]{20,})", re.I)),
    ("album", re.compile(r"/(?:album|browse/album)/([0-9]{6,})", re.I)),
    ("track", re.compile(r"/(?:track|browse/track)/([0-9]{6,})", re.I)),
    ("mix", re.compile(r"/mix/track/([0-9a-f-]{20,})", re.I)),
    ("artist", re.compile(r"/(?:artist|browse/artist)/([0-9]{6,})", re.I)),
]


@dataclass
class TrackInfo:
    track_id: int
    title: str
    artists: List[str]
    album: str
    album_id: int
    cover_id: Optional[str]
    duration: int
    isrc: Optional[str]
    track_number: Optional[int]
    disc_number: Optional[int]
    release_date: Optional[str]
    explicit: bool


def parse_url(url: str) -> tuple[str, str]:
    """Identify the kind of Tidal entity referenced by a URL.

    Returns a (kind, id) tuple. Raises ValueError if the URL is not recognised.
    """
    parsed = urlparse(url.strip())
    if not parsed.netloc or "tidal.com" not in parsed.netloc:
        raise ValueError(f"Not a Tidal URL: {url!r}")
    for kind, pattern in URL_PATTERNS:
        match = pattern.search(parsed.path)
        if match:
            return kind, match.group(1)
    raise ValueError(f"Could not recognise Tidal URL: {url!r}")


def _track_to_info(track: tidalapi.Track) -> TrackInfo:
    artists = [a.name for a in (track.artists or [])]
    if not artists and track.artist:
        artists = [track.artist.name]
    return TrackInfo(
        track_id=track.id,
        title=track.name,
        artists=artists,
        album=track.album.name if track.album else "",
        album_id=track.album.id if track.album else 0,
        cover_id=track.album.cover if track.album else None,
        duration=track.duration,
        isrc=track.isrc,
        track_number=track.track_num,
        disc_number=getattr(track, "volume_num", None),
        release_date=str(track.album.release_date) if track.album and track.album.release_date else None,
        explicit=bool(track.explicit),
    )


def fetch_playlist(session: tidalapi.Session, playlist_id: str) -> tuple[List[TrackInfo], str]:
    """Resolve a playlist identifier to a list of tracks and its name."""
    playlist = session.playlist(playlist_id)
    name = playlist.name
    items: List[TrackInfo] = []
    for track in playlist.tracks():
        if isinstance(track, tidalapi.Track):
            items.append(_track_to_info(track))
    return items, name


def fetch_album(session: tidalapi.Session, album_id: str) -> tuple[List[TrackInfo], str]:
    album = session.album(album_id)
    name = album.name
    items: List[TrackInfo] = []
    for track in album.tracks():
        if isinstance(track, tidalapi.Track):
            items.append(_track_to_info(track))
    return items, name


def fetch_track(session: tidalapi.Session, track_id: str) -> TrackInfo:
    return _track_to_info(session.track(track_id))


def fetch_mix(session: tidalapi.Session, mix_id: str) -> tuple[List[TrackInfo], str]:
    mix = session.mix(mix_id)
    name = mix.title if hasattr(mix, "title") else "Mix"
    items: List[TrackInfo] = []
    for track in mix.items():
        if isinstance(track, tidalapi.Track):
            items.append(_track_to_info(track))
    return items, name


def fetch_artist_top_tracks(session: tidalapi.Session, artist_id: str) -> tuple[List[TrackInfo], str]:
    artist = session.artist(artist_id)
    name = artist.name
    items: List[TrackInfo] = []
    for track in artist.get_top_tracks():
        if isinstance(track, tidalapi.Track):
            items.append(_track_to_info(track))
    return items, name


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #

def model_url(kind: str, model_id) -> str:
    """Build a canonical Tidal URL for a search result."""
    base = {
        "track":    "https://tidal.com/track",
        "album":    "https://tidal.com/album",
        "playlist": "https://tidal.com/playlist",
        "artist":   "https://tidal.com/artist",
        "video":    "https://tidal.com/video",
    }
    return f"{base.get(kind, 'https://tidal.com')}/{model_id}"


def _image_id(model) -> Optional[str]:
    """Best-effort cover/picture id from any Tidal model."""
    for attr in ("cover", "image", "picture"):
        val = getattr(model, attr, None)
        if isinstance(val, str) and val:
            return val
    return None


def _duration_str(seconds: int) -> str:
    if not seconds:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    if minutes >= 60:
        h, m = divmod(minutes, 60)
        return f"{h}:{m:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def search(session: tidalapi.Session, query: str, limit: int = 8) -> list[dict]:
    """Search Tidal and return a normalised, URL-tagged result list."""
    query = (query or "").strip()
    if not query:
        return []

    try:
        results = session.search(query, limit=limit)
    except Exception as exc:
        LOG.warning("Tidal search failed: %s", exc)
        return []

    # tidalapi 0.8.x returns a plain dict: {"artists": [...], "albums": [...],
    # "tracks": [...], "videos": [...], "playlists": [...], "top_hit": ...}
    # Older versions return a SearchResults object with the same attributes.
    # Support both transparently.
    def pick(key):
        if isinstance(results, dict):
            return results.get(key, []) or []
        return getattr(results, key, []) or []

    items: list[dict] = []

    def push(kind, model, title, subtitle):
        if model is None:
            return
        # Tidal uses integer IDs for tracks/albums/videos and UUID strings
        # for playlists/artists. Both work in the canonical URL.
        mid = getattr(model, "id", None)
        if mid is None:
            return
        items.append({
            "kind": kind,
            "id": str(mid),
            "title": title or "",
            "subtitle": subtitle or "",
            "image_id": _image_id(model),
            "url": model_url(kind, mid),
        })

    for track in pick("tracks"):
        if not isinstance(track, tidalapi.Track):
            continue
        artists = ", ".join(a.name for a in (track.artists or [])) or (
            track.artist.name if track.artist else ""
        )
        album = track.album.name if track.album else ""
        parts = []
        if artists: parts.append(artists)
        if album:   parts.append(album)
        duration = getattr(track, "duration", 0)
        parts.append(_duration_str(duration))
        push("track", track, track.name, " · ".join(parts))

    for album in pick("albums"):
        if not isinstance(album, tidalapi.Album):
            continue
        artists = ", ".join(a.name for a in (album.artists or [])) or (
            album.artist.name if album.artist else ""
        )
        parts = []
        if artists: parts.append(artists)
        parts.append(f"{album.num_tracks or 0} tracks")
        push("album", album, album.name, " · ".join(parts))

    for pl in pick("playlists"):
        if not isinstance(pl, tidalapi.Playlist):
            continue
        creator = getattr(pl.creator, "name", "") if pl.creator else ""
        parts = []
        if creator: parts.append(creator)
        parts.append(f"{pl.num_tracks or 0} tracks")
        push("playlist", pl, pl.name, " · ".join(parts))

    for artist in pick("artists"):
        if not isinstance(artist, tidalapi.Artist):
            continue
        push("artist", artist, artist.name, "Artist")

    for vid in pick("videos"):
        if not isinstance(vid, tidalapi.Video):
            continue
        artists = ", ".join(a.name for a in (vid.artists or [])) or (
            vid.artist.name if vid.artist else ""
        )
        duration = getattr(vid, "duration", 0)
        parts = []
        if artists: parts.append(artists)
        parts.append(_duration_str(duration))
        push("video", vid, vid.name, " · ".join(parts))

    return items[: limit * 4]


def resolve_url(session: tidalapi.Session, url: str) -> tuple[List[TrackInfo], str]:
    """Resolve a Tidal URL into a list of tracks and a friendly name."""
    kind, entity_id = parse_url(url)
    if kind == "playlist":
        return fetch_playlist(session, entity_id)
    if kind == "album":
        return fetch_album(session, entity_id)
    if kind == "track":
        return [fetch_track(session, entity_id)], "Single"
    if kind == "mix":
        return fetch_mix(session, entity_id)
    if kind == "artist":
        return fetch_artist_top_tracks(session, entity_id)
    raise ValueError(f"Unsupported URL kind: {kind}")


def fetch_cover(session: tidalapi.Session, cover_id: Optional[str]) -> Optional[bytes]:
    if not cover_id:
        return None
    return session.config.image_client.get(cover_id)
