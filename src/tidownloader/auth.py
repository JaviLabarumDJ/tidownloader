"""Authentication handling for Tidal using OAuth device code flow."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import tidalapi

CONFIG_DIR = Path.home() / ".config" / "tidownloader"
SESSION_FILE = CONFIG_DIR / "session.json"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _session_to_dict(session: tidalapi.Session) -> dict:
    if session.access_token is None:
        raise RuntimeError("Cannot serialize unauthenticated session")
    expiry = session.expiry_time
    if isinstance(expiry, datetime):
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        expiry = expiry.isoformat()
    return {
        "token_type": session.token_type,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expiry_time": expiry,
    }


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _dict_to_session(data: dict) -> tidalapi.Session:
    session = tidalapi.Session()
    session.load_oauth_session(
        data["token_type"],
        data["access_token"],
        data.get("refresh_token"),
        _coerce_datetime(data.get("expiry_time")),
    )
    return session


def load_session() -> Optional[tidalapi.Session]:
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text())
        return _dict_to_session(data)
    except Exception:
        return None


def save_session(session: tidalapi.Session) -> None:
    ensure_config_dir()
    SESSION_FILE.write_text(
        json.dumps(_session_to_dict(session), indent=2, default=_json_default)
    )
    os.chmod(SESSION_FILE, 0o600)


def clear_session() -> None:
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def login() -> tidalapi.Session:
    """Authenticate with Tidal using the OAuth device code flow.

    Prints a verification URL and user code. The user must visit the URL,
    enter the code, and authorize the application. The function blocks
    until authorization completes (or the timeout is reached).
    """
    existing = load_session()
    if existing is not None and existing.check_login():
        return existing

    session = tidalapi.Session()
    print("A new Tidal session needs to be created.")
    try:
        login_obj, future = session.login_oauth()
    except Exception as exc:
        raise RuntimeError(
            f"Failed to start OAuth login: {exc}\n"
            "Make sure you have a working internet connection."
        ) from exc

    print()
    print(f"  Visit:    {login_obj.verification_uri_complete}")
    print(f"  Code:     {login_obj.user_code}")
    print()
    print("Waiting for authorization (this may take a minute)...")

    try:
        future.result()
    except Exception as exc:
        raise RuntimeError(
            "Login failed or timed out. "
            f"Details: {exc}. Please run `tidownloader --login` to try again."
        ) from exc

    if session.access_token is None:
        raise RuntimeError("Authentication failed: no access token received.")

    save_session(session)
    print(f"Session saved to {SESSION_FILE}")
    return session
