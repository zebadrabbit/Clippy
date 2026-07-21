"""Tests for clippy.twitch_ingest — the Twitch Helix API layer.

Everything here is network code, so the whole module is exercised against a
fake ``requests``. The cases that matter are the ones a real user hits: bad
credentials, an expired token, a rate limit mid-pagination, and a broadcaster
that does not exist.
"""

from __future__ import annotations

import pytest
import requests

import clippy.twitch_ingest as ti


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload


class Calls(list):
    """Recorded requests, with a ``queue`` of responses to serve."""

    queue: list


@pytest.fixture
def calls(monkeypatch):
    """Record every outbound request and serve queued responses."""
    recorded = Calls()
    queue: list[FakeResponse] = []

    def _get(url, params=None, headers=None, timeout=None):
        recorded.append({"method": "GET", "url": url, "params": params, "headers": headers})
        return queue.pop(0) if queue else FakeResponse(200, {"data": []})

    def _post(url, params=None, headers=None, timeout=None):
        recorded.append({"method": "POST", "url": url, "params": params})
        return queue.pop(0) if queue else FakeResponse(200, {"access_token": "tok"})

    monkeypatch.setattr(ti.requests, "get", _get)
    monkeypatch.setattr(ti.requests, "post", _post)
    recorded.queue = queue
    return recorded


class TestAppAccessToken:
    def test_returns_the_token(self, calls):
        calls.queue.append(FakeResponse(200, {"access_token": "abc123"}))
        assert ti.get_app_access_token("cid", "secret") == "abc123"

    def test_sends_client_credentials_grant(self, calls):
        calls.queue.append(FakeResponse(200, {"access_token": "abc123"}))
        ti.get_app_access_token("cid", "secret")
        assert calls[0]["params"]["grant_type"] == "client_credentials"
        assert calls[0]["params"]["client_id"] == "cid"

    def test_bad_credentials_raise_with_the_status(self, calls):
        """The most common first-run failure: wrong client id/secret."""
        calls.queue.append(FakeResponse(401, {}, text="invalid client"))
        with pytest.raises(RuntimeError, match="401"):
            ti.get_app_access_token("cid", "nope")

    def test_secret_is_not_leaked_in_the_error(self, calls):
        calls.queue.append(FakeResponse(403, {}, text="forbidden"))
        with pytest.raises(RuntimeError) as exc:
            ti.get_app_access_token("cid", "SUPERSECRET")
        assert "SUPERSECRET" not in str(exc.value)


class TestResolveUser:
    def test_returns_the_first_match(self, calls):
        calls.queue.append(FakeResponse(200, {"data": [{"id": "42", "login": "someone"}]}))
        assert ti.resolve_user("someone", "cid", "tok")["id"] == "42"

    def test_unknown_broadcaster_returns_none(self, calls):
        """Helix answers 200 with an empty list for a login that does not exist."""
        calls.queue.append(FakeResponse(200, {"data": []}))
        assert ti.resolve_user("ghost", "cid", "tok") is None

    def test_error_status_returns_none(self, calls):
        calls.queue.append(FakeResponse(401, {}))
        assert ti.resolve_user("someone", "cid", "tok") is None

    def test_sends_auth_headers(self, calls):
        calls.queue.append(FakeResponse(200, {"data": [{"id": "1"}]}))
        ti.resolve_user("someone", "cid", "tok")
        assert calls[0]["headers"]["Client-ID"] == "cid"
        assert calls[0]["headers"]["Authorization"] == "Bearer tok"


def _clip(i: int) -> dict:
    return {"id": f"clip{i}", "view_count": i, "creator_id": "c1"}


class TestFetchClips:
    def test_follows_the_pagination_cursor(self, calls):
        calls.queue.extend(
            [
                FakeResponse(200, {"data": [_clip(1), _clip(2)], "pagination": {"cursor": "AA"}}),
                FakeResponse(200, {"data": [_clip(3)], "pagination": {}}),
            ]
        )
        got = ti.fetch_clips("bid", "cid", "tok", max_clips=10, page_size=2)
        assert [c["id"] for c in got] == ["clip1", "clip2", "clip3"]
        assert calls[1]["params"]["after"] == "AA", "second page must send the cursor"

    def test_stops_when_no_cursor_is_returned(self, calls):
        calls.queue.append(FakeResponse(200, {"data": [_clip(1)]}))
        assert len(ti.fetch_clips("bid", "cid", "tok", max_clips=50)) == 1
        assert len(calls) == 1

    def test_stops_on_an_empty_page(self, calls):
        calls.queue.append(FakeResponse(200, {"data": [], "pagination": {"cursor": "AA"}}))
        assert ti.fetch_clips("bid", "cid", "tok", max_clips=50) == []

    def test_never_returns_more_than_max_clips(self, calls):
        calls.queue.append(
            FakeResponse(
                200, {"data": [_clip(i) for i in range(10)], "pagination": {"cursor": "AA"}}
            )
        )
        assert len(ti.fetch_clips("bid", "cid", "tok", max_clips=3, page_size=10)) == 3

    def test_page_size_shrinks_to_the_remaining_need(self, calls):
        """`first` must never ask for more than we still want."""
        calls.queue.extend(
            [
                FakeResponse(200, {"data": [_clip(1), _clip(2)], "pagination": {"cursor": "AA"}}),
                FakeResponse(200, {"data": [_clip(3)], "pagination": {"cursor": "BB"}}),
            ]
        )
        ti.fetch_clips("bid", "cid", "tok", max_clips=3, page_size=2)
        assert calls[0]["params"]["first"] == 2
        assert calls[1]["params"]["first"] == 1

    def test_rate_limit_returns_what_was_collected(self, calls):
        """A 429 partway through keeps the earlier pages rather than losing them."""
        calls.queue.extend(
            [
                FakeResponse(200, {"data": [_clip(1)], "pagination": {"cursor": "AA"}}),
                FakeResponse(429, {}, text="Too Many Requests"),
            ]
        )
        got = ti.fetch_clips("bid", "cid", "tok", max_clips=10, page_size=1)
        assert [c["id"] for c in got] == ["clip1"]

    def test_expired_token_yields_no_clips_rather_than_raising(self, calls):
        calls.queue.append(FakeResponse(401, {}, text="invalid oauth token"))
        assert ti.fetch_clips("bid", "cid", "expired", max_clips=10) == []

    def test_time_window_is_passed_through(self, calls):
        calls.queue.append(FakeResponse(200, {"data": [_clip(1)]}))
        ti.fetch_clips(
            "bid", "cid", "tok", started_at="2025-07-01T00:00:00Z", ended_at="2025-07-07T00:00:00Z"
        )
        assert calls[0]["params"]["started_at"] == "2025-07-01T00:00:00Z"
        assert calls[0]["params"]["ended_at"] == "2025-07-07T00:00:00Z"

    def test_window_keys_are_omitted_when_unset(self, calls):
        calls.queue.append(FakeResponse(200, {"data": [_clip(1)]}))
        ti.fetch_clips("bid", "cid", "tok")
        assert "started_at" not in calls[0]["params"]
        assert "ended_at" not in calls[0]["params"]


class TestFetchClipsByIds:
    def test_no_request_for_an_empty_list(self, calls):
        assert ti.fetch_clips_by_ids([], "cid", "tok") == []
        assert calls == []

    def test_blank_ids_are_dropped(self, calls):
        calls.queue.append(FakeResponse(200, {"data": [_clip(1)]}))
        ti.fetch_clips_by_ids(["a", "", None], "cid", "tok")
        assert [v for k, v in calls[0]["params"] if k == "id"] == ["a"]

    def test_chunks_at_the_helix_limit_of_100(self, calls):
        calls.queue.extend([FakeResponse(200, {"data": []}), FakeResponse(200, {"data": []})])
        ti.fetch_clips_by_ids([f"c{i}" for i in range(150)], "cid", "tok")
        assert len(calls) == 2
        assert len(calls[0]["params"]) == 100
        assert len(calls[1]["params"]) == 50

    def test_a_failed_chunk_does_not_lose_the_others(self, calls):
        calls.queue.extend([FakeResponse(500, {}), FakeResponse(200, {"data": [_clip(9)]})])
        got = ti.fetch_clips_by_ids([f"c{i}" for i in range(150)], "cid", "tok")
        assert [c["id"] for c in got] == ["clip9"]

    def test_network_error_is_survivable(self, calls, monkeypatch):
        def boom(*a, **kw):
            raise requests.RequestException("connection reset")

        monkeypatch.setattr(ti.requests, "get", boom)
        assert ti.fetch_clips_by_ids(["a"], "cid", "tok") == []


class TestFetchCreatorAvatars:
    def test_maps_creator_id_to_profile_image(self, calls):
        calls.queue.append(
            FakeResponse(200, {"data": [{"id": "c1", "profile_image_url": "http://img/1.png"}]})
        )
        got = ti.fetch_creator_avatars([{"creator_id": "c1"}], "cid", "tok")
        assert got == {"c1": "http://img/1.png"}

    def test_duplicate_creators_are_requested_once(self, calls):
        calls.queue.append(FakeResponse(200, {"data": []}))
        ti.fetch_creator_avatars([{"creator_id": "c1"}] * 5, "cid", "tok")
        assert len([v for k, v in calls[0]["params"] if k == "id"]) == 1

    def test_no_creators_means_no_request(self, calls):
        assert ti.fetch_creator_avatars([{}], "cid", "tok") == {}
        assert calls == []

    def test_failure_yields_an_empty_map_not_a_crash(self, calls):
        calls.queue.append(FakeResponse(401, {}))
        assert ti.fetch_creator_avatars([{"creator_id": "c1"}], "cid", "tok") == {}


class TestBuildClipRows:
    def _raw(self, **over):
        base = {
            "id": "abc",
            "created_at": "2025-07-01T12:00:00Z",
            "creator_name": "Streamer",
            "creator_id": "c1",
            "view_count": 250,
            "url": "https://clips.twitch.tv/abc",
            "title": "nice play",
            "duration": 30.5,
            "thumbnail_url": "http://thumb/abc.jpg",
        }
        base.update(over)
        return base

    def test_maps_the_helix_payload(self):
        row = ti.build_clip_rows([self._raw()])[0]
        assert row.id == "abc"
        assert row.author == "Streamer"
        assert row.view_count == 250
        assert row.url == "https://clips.twitch.tv/abc"
        assert row.duration == 30.5

    def test_created_at_becomes_an_epoch(self):
        row = ti.build_clip_rows([self._raw()])[0]
        from datetime import datetime, timezone

        expected = datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc).timestamp()
        assert row.created_ts == expected

    def test_avatar_map_wins_over_the_thumbnail_fallback(self):
        row = ti.build_clip_rows([self._raw()], {"c1": "http://img/real.png"})[0]
        assert row.avatar_url == "http://img/real.png"

    def test_thumbnail_is_used_when_no_avatar_is_known(self):
        row = ti.build_clip_rows([self._raw()], {})[0]
        assert row.avatar_url == "http://thumb/abc.jpg"

    def test_string_numerics_are_coerced(self):
        row = ti.build_clip_rows([self._raw(view_count="17", duration="12")])[0]
        assert row.view_count == 17 and row.duration == 12.0

    def test_a_malformed_clip_does_not_sink_the_batch(self):
        rows = ti.build_clip_rows([self._raw(view_count="not-a-number"), self._raw(id="ok")])
        assert [r.id for r in rows] == ["ok"]


class TestLoadCredentials:
    def test_cli_args_win(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TWITCH_CLIENT_ID", "env-id")
        monkeypatch.setenv("TWITCH_CLIENT_SECRET", "env-secret")
        assert ti.load_credentials("cli-id", "cli-secret") == ("cli-id", "cli-secret")

    def test_environment_is_used_when_no_args(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TWITCH_CLIENT_ID", "env-id")
        monkeypatch.setenv("TWITCH_CLIENT_SECRET", "env-secret")
        assert ti.load_credentials(None, None) == ("env-id", "env-secret")

    def test_dotenv_is_the_last_resort(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
        monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
        (tmp_path / ".env").write_text(
            'TWITCH_CLIENT_ID="file-id"\nTWITCH_CLIENT_SECRET=file-secret\n', encoding="utf-8"
        )
        assert ti.load_credentials(None, None) == ("file-id", "file-secret")

    def test_dotenv_ignores_comments_and_junk(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
        monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
        (tmp_path / ".env").write_text(
            "# a comment\n\nnot-a-pair\nTWITCH_CLIENT_ID=x\nTWITCH_CLIENT_SECRET=y\n",
            encoding="utf-8",
        )
        assert ti.load_credentials(None, None) == ("x", "y")

    def test_missing_credentials_exit_with_guidance(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
        monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
        with pytest.raises(SystemExit) as exc:
            ti.load_credentials(None, None)
        assert "TWITCH_CLIENT_ID" in str(exc.value)
