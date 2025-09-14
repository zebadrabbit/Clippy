"""Twitch Helix clip ingestion utilities.

Fetches clips directly from the Twitch API (Helix) and stores them in the
existing `Messages` table so the downstream pipeline (normalization, overlay,
concatenation) can run without the Discord scraping layer.

Schema expectation (created if absent):
    CREATE TABLE IF NOT EXISTS Messages (
        id TEXT PRIMARY KEY,          -- Twitch clip id
        datetime REAL,                -- creation timestamp (epoch seconds)
        author TEXT,                  -- clip creator display name
        avatar TEXT,                  -- creator profile image URL (if resolved)
        reactions INTEGER,            -- reused column: stores view_count
        url TEXT                      -- clip URL
    )

Environment variables (recommended):
    TWITCH_CLIENT_ID
    TWITCH_CLIENT_SECRET

Fallback: values can be passed via CLI flags in `main.py`.
"""

from __future__ import annotations

import os
import time
import typing as _t
import requests
from clippy.utils import log, fix_ascii

HelixHeaders = _t.Dict[str, str]

AUTH_URL = "https://id.twitch.tv/oauth2/token"
CLIPS_URL = "https://api.twitch.tv/helix/clips"
USERS_URL = "https://api.twitch.tv/helix/users"


def get_app_access_token(client_id: str, client_secret: str) -> str:
    """Obtain an app access token (client credentials flow)."""
    resp = requests.post(
        AUTH_URL,
        params={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OAuth token request failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["access_token"]


def _headers(client_id: str, token: str) -> HelixHeaders:
    return {"Client-ID": client_id, "Authorization": f"Bearer {token}"}


def resolve_user(login: str, client_id: str, token: str) -> dict | None:
    """Resolve a user by login name; returns first match or None."""
    resp = requests.get(USERS_URL, params={"login": login}, headers=_headers(client_id, token), timeout=15)
    if resp.status_code != 200:
        log(f"Resolve user failed: {login} {resp.status_code}", 5)
        return None
    data = resp.json().get("data", [])
    return data[0] if data else None


def fetch_clips(
    broadcaster_id: str,
    client_id: str,
    token: str,
    started_at: str | None = None,
    ended_at: str | None = None,
    max_clips: int = 100,
    page_size: int = 20,
) -> _t.List[dict]:
    """Fetch up to `max_clips` recent clips for a broadcaster within an optional time window.

    Times must be RFC3339 (ISO8601) strings when provided.
    """
    clips: _t.List[dict] = []
    cursor = None
    while len(clips) < max_clips:
        params = {"broadcaster_id": broadcaster_id, "first": min(page_size, max_clips - len(clips))}
        if started_at:
            params["started_at"] = started_at
        if ended_at:
            params["ended_at"] = ended_at
        if cursor:
            params["after"] = cursor
        # Log effective request parameters (no secrets)
        try:
            _sa = params.get("started_at") or "-"
            _ea = params.get("ended_at") or "-"
            _af = params.get("after") or "-"
            _first = params.get("first")
            log(
                "Helix params: "
                + "started_at=" + str(_sa)
                + " ended_at=" + str(_ea)
                + " first=" + str(_first)
                + " after=" + str(_af),
                2,
            )
        except Exception:
            pass
        resp = requests.get(CLIPS_URL, params=params, headers=_headers(client_id, token), timeout=30)
        if resp.status_code != 200:
            log(f"Error fetching clips: {resp.status_code} {resp.text[:120]}", 5)
            break
        payload = resp.json()
        data = payload.get("data", [])
        if not data:
            break
        clips.extend(data)
        cursor = payload.get("pagination", {}).get("cursor")
        if not cursor:
            break
    return clips[:max_clips]


def fetch_creator_avatars(clips: _t.Iterable[dict], client_id: str, token: str) -> dict:
    """Batch fetch profile_image_url for creator_ids in the clip list."""
    ids = {c.get("creator_id") for c in clips if c.get("creator_id")}
    if not ids:
        return {}
    avatar_map: dict[str, str] = {}
    id_list = list(ids)
    for i in range(0, len(id_list), 100):  # Helix limit
        chunk = id_list[i:i+100]
        params = [("id", cid) for cid in chunk]
        resp = requests.get(USERS_URL, params=params, headers=_headers(client_id, token), timeout=15)
        if resp.status_code != 200:
            log(f"Avatar batch failed {resp.status_code}", 5)
            continue
        for u in resp.json().get("data", []):
            avatar_map[u.get("id")] = u.get("profile_image_url", "")
    return avatar_map


def build_clip_rows(clips: _t.Iterable[dict], avatar_map: dict | None = None) -> list[tuple[str, float, str, str, int, str]]:
    """Convert raw Helix clip dicts to pipeline tuple rows.

    Tuple: (id, epoch_ts, author, avatar_url, view_count, url)
    """
    rows: list[tuple[str, float, str, str, int, str]] = []
    for c in clips:
        try:
            ts = _iso_to_epoch(c.get("created_at", ""))
            creator_id = c.get("creator_id")
            avatar_url = ""
            if avatar_map and creator_id in avatar_map:
                avatar_url = avatar_map[creator_id]
            else:
                avatar_url = c.get("thumbnail_url", "")  # fallback
            rows.append((
                c.get("id", "unknown"),
                ts,
                fix_ascii(c.get("creator_name", "unknown")),
                avatar_url,
                int(c.get("view_count", 0)),
                c.get("url", ""),
            ))
        except Exception as e:  # pragma: no cover
            log(f"Row build error: {e}", 5)
    return rows


def _iso_to_epoch(iso_str: str) -> float:
    # Twitch returns ISO8601 with timezone Z e.g. 2024-07-10T12:34:56Z
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return time.time()


def _load_dotenv(path: str = ".env") -> dict:
    """Lightweight .env parser (no external dependency)."""
    data: dict[str, str] = {}
    if not os.path.isfile(path):
        return data
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:  # pragma: no cover
        log(f".env parse error: {e}", 5)
    return data


def load_credentials(arg_client_id: str | None, arg_client_secret: str | None) -> tuple[str, str]:
    # Precedence: CLI args > real environment > .env file
    env_file = _load_dotenv()
    cid = arg_client_id or os.getenv("TWITCH_CLIENT_ID") or env_file.get("TWITCH_CLIENT_ID")
    secret = arg_client_secret or os.getenv("TWITCH_CLIENT_SECRET") or env_file.get("TWITCH_CLIENT_SECRET")
    if not cid or not secret:
        raise SystemExit(
            "Missing Twitch credentials: set TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET, provide --client-id/--client-secret, or add them to .env"
        )
    return cid, secret
