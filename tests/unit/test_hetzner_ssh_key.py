# region MODULE_CONTRACT
# PURPOSE: Unit tests for hetzner.ensure_ssh_key — GET-first registration with POST-on-miss.
# SCOPE: ensure_ssh_key with mocked aiohttp session; no network.
# KEYWORDS: ensure_ssh_key, duplicate-key recovery, hetzner API, aiohttp
# endregion MODULE_CONTRACT

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.infra.cloud.providers.hetzner import (
    HetznerError,
    ensure_ssh_key,
)


def _make_mock_resp(status: int, json_data: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def _hetz_err(code: str, message: str = "err", status: int = 409) -> dict:
    return {"error": {"code": code, "message": message}}


def _make_key() -> MagicMock:
    """Mock ASSHKey with the surface ensure_ssh_key touches."""
    key = MagicMock()
    key.export_public_key.return_value = b"ssh-rsa AAAA test"
    # get_fingerprint("md5") -> "MD5:aa:bb:cc"; .split(":", 1)[1] -> "aa:bb:cc"
    key.get_fingerprint.return_value = "MD5:aa:bb:cc"
    return key


def _ssh_key(key_id: int = 1, name: str = "yakey-abc") -> dict:
    return {"id": key_id, "name": name, "fingerprint": "aa:bb:cc:dd:ee"}


def _ssh_keys_list_empty() -> dict:
    return {"ssh_keys": []}


def _ssh_keys_list(key: dict) -> dict:
    return {"ssh_keys": [key]}


def _ssh_key_create(key_id: int = 1, name: str = "yakey-abc") -> dict:
    return {"ssh_key": _ssh_key(key_id, name)}


def _make_session_with_queue(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.request = MagicMock(side_effect=list(responses))
    return session


class TestEnsureSshKey:
    """ensure_ssh_key() — GET-first registration with POST-on-miss."""

    @pytest.mark.asyncio
    async def test_existing_key_found_via_fingerprint_get(self) -> None:
        """Common path: the key is already registered; one GET resolves it."""
        found = _make_mock_resp(200, _ssh_keys_list(_ssh_key(key_id=4242)))
        session = _make_session_with_queue([found])

        result = await ensure_ssh_key(session, _make_key(), "yakey-abc")

        assert result == 4242
        session.request.assert_called_once()
        call = session.request.call_args
        assert call.args[0] == "GET"
        assert call.kwargs.get("params", {}).get("fingerprint") == "aa:bb:cc"

    @pytest.mark.asyncio
    async def test_new_key_registered_via_post_on_miss(self) -> None:
        """First-ever registration: GET empty → POST 201."""
        empty = _make_mock_resp(200, _ssh_keys_list_empty())
        created = _make_mock_resp(201, _ssh_key_create(key_id=42))
        session = _make_session_with_queue([empty, created])

        result = await ensure_ssh_key(session, _make_key(), "yakey-abc")

        assert result == 42
        assert session.request.call_count == 2
        second = session.request.call_args_list[1]
        assert second.args[0] == "POST"
        assert second.args[1].endswith("/ssh_keys")

    @pytest.mark.asyncio
    async def test_unrelated_api_error_reraised(self) -> None:
        """A non-uniqueness POST error is re-raised, not swallowed."""
        empty = _make_mock_resp(200, _ssh_keys_list_empty())
        bad = _make_mock_resp(400, _hetz_err("invalid_input", "bad token", 400))
        session = _make_session_with_queue([empty, bad])

        with pytest.raises(HetznerError):
            await ensure_ssh_key(session, _make_key(), "yakey-abc")

        assert session.request.call_count == 2

    @pytest.mark.asyncio
    async def test_invalid_ssh_keys_list_response_raises(self) -> None:
        """Malformed GET /ssh_keys response raises HetznerError."""
        malformed = _make_mock_resp(200, {"not_ssh_keys": []})
        session = _make_session_with_queue([malformed])

        with pytest.raises(HetznerError, match="Invalid SSH keys list response"):
            await ensure_ssh_key(session, _make_key(), "yakey-abc")

    @pytest.mark.asyncio
    async def test_invalid_ssh_key_create_response_raises(self) -> None:
        """Malformed POST /ssh_keys response raises HetznerError."""
        empty = _make_mock_resp(200, _ssh_keys_list_empty())
        malformed = _make_mock_resp(201, {"ssh_key": {"id": "not-an-int"}})
        session = _make_session_with_queue([empty, malformed])

        with pytest.raises(HetznerError, match="Invalid SSH key create response"):
            await ensure_ssh_key(session, _make_key(), "yakey-abc")
