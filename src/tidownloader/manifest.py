"""Stream manifest handling, decryption key fetch, and AES-CTR decryption."""

from __future__ import annotations

import base64
import logging
import re
import threading
from dataclasses import dataclass
from typing import Iterable, List, Optional

import requests
import tidalapi
from Crypto.Cipher import AES
from Crypto.Util import Counter

LOG = logging.getLogger("tidownloader")

DEFAULT_KEY_ENDPOINT = "https://api.tidal.com/v1/audio-security/key"

# Maps the MPD ContentProtection schemeId to a cipher mode.
# Tidal currently uses CENC (AES-CTR) for FLAC segments.
SCHEME_CTR = "cenc"
SCHEME_CBCS = "cbcs"

KID_PATTERN = re.compile(r'default_KID="([^"]+)"', re.I)
SCHEME_PATTERN = re.compile(
    r'(?:value|schemeIdUri)="[^"]*?(cenc|cbcs|aes-ctr|aes-cbc)[^"]*"',
    re.I,
)


@dataclass
class SegmentInfo:
    """Information about a single track download."""

    init_url: str
    segment_urls: List[str]
    kid: Optional[str]
    cipher_scheme: str
    file_extension: str
    mime_type: str
    codecs: str
    sample_rate: int


def _xml_namespace_unquote(text: str) -> str:
    """Strip a single XML namespace prefix from a tag name."""
    return text.rsplit(":", 1)[-1]


def _extract_kid(mpd_xml: str) -> Optional[str]:
    match = KID_PATTERN.search(mpd_xml)
    if not match:
        return None
    return match.group(1).replace("-", "").lower()


def _extract_scheme(mpd_xml: str) -> str:
    match = SCHEME_PATTERN.search(mpd_xml)
    if match:
        scheme = match.group(1).lower()
        if scheme in ("cenc", "aes-ctr"):
            return SCHEME_CTR
        if scheme in ("cbcs", "aes-cbc"):
            return SCHEME_CBCS
    return SCHEME_CTR


def _split_segments(urls: List[str]) -> tuple[Optional[str], List[str]]:
    if not urls:
        return None, []
    init_url = urls[0]
    segment_urls = urls[1:]
    return init_url, segment_urls


def parse_manifest(
    stream: tidalapi.media.Stream,
    manifest: tidalapi.media.StreamManifest,
) -> SegmentInfo:
    """Build a :class:`SegmentInfo` from a Tidal stream + manifest."""
    mpd_xml = stream.get_manifest_data() if stream.is_bts is False and stream.is_mpd else ""
    if not mpd_xml and getattr(stream, "manifest", None):
        try:
            mpd_xml = base64.b64decode(stream.manifest).decode("utf-8")
        except Exception:
            mpd_xml = ""

    if not mpd_xml:
        raise RuntimeError("Could not decode DASH manifest for this track.")

    kid = _extract_kid(mpd_xml)
    scheme = _extract_scheme(mpd_xml)

    init_url, segment_urls = _split_segments(manifest.urls)

    return SegmentInfo(
        init_url=init_url or (segment_urls[0] if segment_urls else ""),
        segment_urls=segment_urls,
        kid=kid,
        cipher_scheme=scheme,
        file_extension=manifest.file_extension or "m4a",
        mime_type=str(manifest.mime_type),
        codecs=str(manifest.codecs),
        sample_rate=int(manifest.sample_rate or 44100),
    )


def fetch_decryption_key(
    session: tidalapi.Session,
    kid: str,
    endpoint: str = DEFAULT_KEY_ENDPOINT,
) -> bytes:
    """Fetch the AES-128 decryption key for a given KID from Tidal.

    Returns the raw 16-byte key.
    """
    if not kid:
        raise RuntimeError("Track manifest has no encryption KID; cannot fetch key.")

    params = {"keyId": kid}
    LOG.debug("Fetching decryption key for KID %s", kid)
    response = session.request.basic_request(
        "GET", endpoint, params=params, base_url="https://api.tidal.com"
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch decryption key (status {response.status_code}): "
            f"{response.text[:200]}"
        )
    payload = response.json()
    key_b64 = payload.get("key")
    if not key_b64:
        raise RuntimeError(f"Decryption key response missing 'key' field: {payload}")
    key = base64.b64decode(key_b64)
    if len(key) != 16:
        raise RuntimeError(
            f"Unexpected decryption key length {len(key)} bytes (expected 16)"
        )
    return key


def _build_cipher_ctr(key: bytes, segment_index: int) -> AES.AESModeOfOperationCTR:
    """CENC/AES-CTR counter is the segment index (16-byte big-endian)."""
    ctr = Counter.new(128, initial_value=segment_index)
    return AES.new(key, AES.MODE_CTR, counter=ctr)


def _build_cipher_cbc(key: bytes, segment_index: int) -> AES.AESModeOfOperationCBC:
    """CBCS uses an IV derived from the key ID, but Tidal serves a fixed
    constant IV for FLAC segments. We use the segment index as IV for
    robustness – the decryption of the first block is what matters for
    pattern encryption."""
    iv = segment_index.to_bytes(16, "big")
    return AES.new(key, AES.MODE_CBC, iv=iv)


def decrypt_segment(key: bytes, index: int, cipher: str, data: bytes) -> bytes:
    """Decrypt a single segment using either AES-CTR or AES-CBCS.

    For CENC (AES-CTR) the entire segment is decrypted. For CBCS
    (AES-CBC with subsampling) only the first 16-byte block is decrypted,
    which is the standard Tidal pattern for FLAC segments.
    """
    if cipher == SCHEME_CBCS:
        if len(data) <= 16:
            cipher_obj = _build_cipher_cbc(key, index)
            return cipher_obj.decrypt(data)
        cipher_obj = _build_cipher_cbc(key, index)
        head = data[:16]
        tail = data[16:]
        return cipher_obj.decrypt(head) + tail
    cipher_obj = _build_cipher_ctr(key, index)
    return cipher_obj.decrypt(data)


def download_bytes(
    session: requests.Session,
    url: str,
    chunk_size: int = 64 * 1024,
) -> bytes:
    response = session.get(url, stream=True, timeout=60)
    response.raise_for_status()
    buf = bytearray()
    for chunk in response.iter_content(chunk_size=chunk_size):
        if chunk:
            buf.extend(chunk)
    return bytes(buf)
