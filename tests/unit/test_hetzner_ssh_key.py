"""Tests for hetzner.ensure_ssh_key — GET-first registration with POST-on-miss."""
# region MODULE_CONTRACT
# PURPOSE: Unit tests for hetzner.ensure_ssh_key — GET-first registration with POST-on-miss.
# SCOPE: ensure_ssh_key with mocked HetznerClient; no network.
# KEYWORDS: ensure_ssh_key, duplicate-key recovery, hetzner API, HetznerClient
# endregion MODULE_CONTRACT

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.infra.cloud.providers.hetzner import (
    HetznerError,
    ensure_ssh_key,
)


def _make_key() -> MagicMock:
    """Mock ASSHKey with the surface ensure_ssh_key touches."""
    key = MagicMock()
    key.export_public_key.return_value = b"ssh-rsa AAAA test"
    # get_fingerprint("md5") -> "MD5:aa:bb:cc"; .split(":", 1)[1] -> "aa:bb:cc"
    key.get_fingerprint.return_value = "MD5:aa:bb:cc"
    return key


def _ssh_key_stream(items: list):
    """Build an async generator mimicking HetznerClient.get_ssh_keys."""

    async def gen():
        for key in items:
            yield key

    return gen()


class TestEnsureSshKey:
    """ensure_ssh_key() — GET-first registration with POST-on-miss."""

    @pytest.mark.asyncio
    async def test_existing_key_found_via_fingerprint_get(self) -> None:
        """Common path: the key is already registered; one GET resolves it."""
        mock_client = MagicMock()
        mock_client.get_ssh_keys = MagicMock(
            return_value=_ssh_key_stream(
                [{"id": 4242, "name": "yakey-abc", "fingerprint": "aa:bb:cc"}]
            )
        )
        mock_client.create_ssh_key = AsyncMock()

        result = await ensure_ssh_key(mock_client, _make_key(), "yakey-abc")

        assert result == 4242
        mock_client.get_ssh_keys.assert_called_once()
        mock_client.create_ssh_key.assert_not_awaited()
        # fingerprint query passed through
        call_kwargs = mock_client.get_ssh_keys.call_args.kwargs
        assert call_kwargs.get("fingerprint") == "aa:bb:cc"

    @pytest.mark.asyncio
    async def test_new_key_registered_via_post_on_miss(self) -> None:
        """First-ever registration: GET empty → POST 201."""
        mock_client = MagicMock()
        mock_client.get_ssh_keys = MagicMock(return_value=_ssh_key_stream([]))
        mock_client.create_ssh_key = AsyncMock(
            return_value={"id": 42, "name": "yakey-abc", "fingerprint": "aa:bb:cc"}
        )

        result = await ensure_ssh_key(mock_client, _make_key(), "yakey-abc")

        assert result == 42
        mock_client.get_ssh_keys.assert_called_once()
        mock_client.create_ssh_key.assert_awaited_once()
        args = mock_client.create_ssh_key.call_args.args
        assert args[0] == "yakey-abc"
        assert args[1] == "ssh-rsa AAAA test"

    @pytest.mark.asyncio
    async def test_unrelated_api_error_reraised(self) -> None:
        """A non-uniqueness POST error is re-raised, not swallowed."""
        mock_client = MagicMock()
        mock_client.get_ssh_keys = MagicMock(return_value=_ssh_key_stream([]))
        mock_client.create_ssh_key = AsyncMock(
            side_effect=HetznerError("invalid_input", status=400)
        )

        with pytest.raises(HetznerError):
            await ensure_ssh_key(mock_client, _make_key(), "yakey-abc")

        assert mock_client.create_ssh_key.await_count == 1


# =============================================================================
# _resolve_ssh_key_by_fingerprint — fingerprint parsing
# =============================================================================


class TestResolveSshKeyFingerprint:
    """_resolve_ssh_key_by_fingerprint — fingerprint prefix handling."""

    @pytest.mark.asyncio
    async def test_md5_prefix_stripped(self) -> None:
        """asyncssh form 'MD5:aa:bb:cc' -> query 'aa:bb:cc'."""
        from yascheduler.infra.cloud.providers.hetzner import (
            _resolve_ssh_key_by_fingerprint,
        )

        key = MagicMock()
        key.get_fingerprint.return_value = "MD5:aa:bb:cc"
        mock_client = MagicMock()
        mock_client.get_ssh_keys = MagicMock(return_value=_ssh_key_stream([]))

        await _resolve_ssh_key_by_fingerprint(mock_client, key)

        call_kwargs = mock_client.get_ssh_keys.call_args.kwargs
        assert call_kwargs.get("fingerprint") == "aa:bb:cc"

    @pytest.mark.asyncio
    async def test_bare_fingerprint_tolerated(self) -> None:
        """Bare fingerprint without 'MD5:' prefix is passed through unchanged.

        Regression for the old split(':', maxsplit=1)[1], which would have
        dropped the first octet ('aa') and queried 'bb:cc' — matching nothing.
        """
        from yascheduler.infra.cloud.providers.hetzner import (
            _resolve_ssh_key_by_fingerprint,
        )

        key = MagicMock()
        key.get_fingerprint.return_value = "aa:bb:cc"
        mock_client = MagicMock()
        mock_client.get_ssh_keys = MagicMock(return_value=_ssh_key_stream([]))

        await _resolve_ssh_key_by_fingerprint(mock_client, key)

        call_kwargs = mock_client.get_ssh_keys.call_args.kwargs
        assert call_kwargs.get("fingerprint") == "aa:bb:cc"
