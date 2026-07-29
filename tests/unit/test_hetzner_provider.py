"""Tests for Hetzner provider orphan-prevention and transient-error handling."""
# region MODULE_CONTRACT
# PURPOSE: Unit tests for hetzner create/delete orphan-prevention, transient-error retry, and retry classification.
# SCOPE: hetzner.py create_node cleanup path, delete_node retry/not_found, _is_retryable classification, _extract_ipv4; aiohttp session mocked.
# KEYWORDS: hetzner, orphan, retry, transient, create, delete, unit
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from yascheduler.infra.cloud.providers.hetzner import HetznerError


class LogCaptureHandler(logging.Handler):
    """Capture log records for assertion."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)


@pytest.fixture
def log_records() -> Generator[list[logging.LogRecord], None, None]:
    """Capture log records from the hetzner provider logger."""
    logger = logging.getLogger("yascheduler.infra.cloud.providers.hetzner")
    records: list[logging.LogRecord] = []
    handler = LogCaptureHandler(records)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _make_mock_resp(status: int, json_data: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def _make_mock_session_with_queue(
    responses: list[MagicMock],
) -> MagicMock:
    """Session whose .request pops responses in order."""
    session = MagicMock()
    session.request = MagicMock(side_effect=list(responses))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _hetz_err(code: str, message: str = "err", status: int = 400) -> dict:
    return {"error": {"code": code, "message": message}}


def _ssh_key(key_id: int = 1, name: str = "yakey-abc") -> dict:
    return {"id": key_id, "name": name, "fingerprint": "aa:bb:cc:dd:ee"}


def _ssh_keys_list_empty() -> dict:
    return {"ssh_keys": []}


def _ssh_keys_list(key: dict) -> dict:
    return {"ssh_keys": [key]}


def _ssh_key_create(key_id: int = 1, name: str = "yakey-abc") -> dict:
    return {"ssh_key": _ssh_key(key_id, name)}


def _ssh_key_dict(key_id: int) -> dict:
    """A realistic Hetzner SSH key object (matches GET/POST /ssh_keys response)."""
    return {
        "id": key_id,
        "name": "yakey-abc",
        "fingerprint": "aa:bb:cc",
        "public_key": "ssh-rsa AAAA test",
    }


def _ssh_keys_empty_resp() -> MagicMock:
    """GET /ssh_keys returning no keys (ensure_ssh_key POST-on-miss path)."""
    return _make_mock_resp(200, {"ssh_keys": []})


def _ssh_key_created_resp(key_id: int) -> MagicMock:
    """POST /ssh_keys 201 response."""
    return _make_mock_resp(201, {"ssh_key": _ssh_key_dict(key_id)})


# =============================================================================
# _is_retryable classification
# =============================================================================


class TestIsRetryable:
    """_is_retryable() — classify which Hetzner errors are retryable per method."""

    def test_429_retryable_for_any_method(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _is_retryable

        exc = _make_err(status=429)
        assert _is_retryable("POST", exc) is True
        assert _is_retryable("DELETE", exc) is True

    def test_5xx_retryable_for_idempotent(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _is_retryable

        for code in (500, 502, 503, 504):
            assert _is_retryable("DELETE", _make_err(status=code)) is True
            assert _is_retryable("GET", _make_err(status=code)) is True

    def test_5xx_not_retryable_for_post(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _is_retryable

        assert _is_retryable("POST", _make_err(status=500)) is False

    def test_4xx_not_retryable_except_429(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _is_retryable

        for code in (400, 403, 404, 409):
            assert _is_retryable("DELETE", _make_err(status=code)) is False

    def test_transport_error_retryable_for_idempotent(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _is_retryable

        exc = _make_err(status=None)
        assert _is_retryable("DELETE", exc) is True
        assert _is_retryable("GET", exc) is True

    def test_transport_error_not_retryable_for_post(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _is_retryable

        assert _is_retryable("POST", _make_err(status=None)) is False


def _make_err(status: int | None, code: str | None = None) -> HetznerError:
    from yascheduler.infra.cloud.providers.hetzner import HetznerError

    return HetznerError("e", code=code, status=status)


# =============================================================================
# _extract_ipv4
# =============================================================================


class TestExtractIpv4:
    """_extract_ipv4() — safely extract public IPv4 from create-server response."""

    def test_happy_path(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _extract_ipv4

        server = {"public_net": {"ipv4": {"ip": "1.2.3.4"}}}
        assert _extract_ipv4(server) == "1.2.3.4"

    def test_missing_public_net(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _extract_ipv4

        assert _extract_ipv4({}) is None
        assert _extract_ipv4({"public_net": None}) is None

    def test_missing_ipv4(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _extract_ipv4

        assert _extract_ipv4({"public_net": {}}) is None

    def test_ip_not_str(self) -> None:
        from yascheduler.infra.cloud.providers.hetzner import _extract_ipv4

        assert _extract_ipv4({"public_net": {"ipv4": {"ip": None}}}) is None


# =============================================================================
# hetzner_create_node orphan-prevention
# =============================================================================


class TestHetznerCreateNodeOrphanPrevention:
    """hetzner_create_node() — never leaks a billable orphan on post-create failure."""

    @pytest.mark.asyncio
    async def test_missing_ipv4_triggers_cleanup_and_raises(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

        cfg = ConfigCloudHetzner(token="test-orphan-ip")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAA test"

        # GET /ssh_keys empty → POST /ssh_keys → POST /servers (no public_net) → DELETE cleanup.
        ssh_keys_empty = _make_mock_resp(200, _ssh_keys_list_empty())
        ssh_key_create = _make_mock_resp(201, _ssh_key_create(1))
        create_resp = _make_mock_resp(
            201,
            {"server": {"id": 99, "public_net": None}},
        )
        delete_resp = _make_mock_resp(200, {})  # DELETE success (JSON body ignored)
        session = _make_mock_session_with_queue(
            [ssh_keys_empty, ssh_key_create, create_resp, delete_resp]
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
                return_value=session,
            ),
            patch(
                "yascheduler.infra.cloud.providers.hetzner.get_key_name",
                return_value="yakey-abc",
            ),
            pytest.raises(RuntimeError, match="without a public IPv4"),
        ):
            await hetzner_create_node(cfg, mock_key)

        assert session.request.call_count == 4
        fourth = session.request.call_args_list[3]
        assert fourth.args[0] == "DELETE"
        assert fourth.args[1].endswith("/servers/99")

    @pytest.mark.asyncio
    async def test_post_create_exception_triggers_cleanup_and_reraises(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

        cfg = ConfigCloudHetzner(token="test-orphan-exc")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAA test"

        ssh_keys_empty = _make_mock_resp(200, _ssh_keys_list_empty())
        ssh_key_create = _make_mock_resp(201, _ssh_key_create(1))
        # public_net.ipv4 malformed (ipv4 is None).
        create_resp = _make_mock_resp(
            201,
            {"server": {"id": 77, "public_net": {"ipv4": None}}},
        )
        delete_resp = _make_mock_resp(200, {})
        session = _make_mock_session_with_queue(
            [ssh_keys_empty, ssh_key_create, create_resp, delete_resp]
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
                return_value=session,
            ),
            patch(
                "yascheduler.infra.cloud.providers.hetzner.get_key_name",
                return_value="yakey-abc",
            ),
            pytest.raises(RuntimeError, match="without a public IPv4"),
        ):
            await hetzner_create_node(cfg, mock_key)

        fourth = session.request.call_args_list[3]
        assert fourth.args[0] == "DELETE"
        assert fourth.args[1].endswith("/servers/77")

    @pytest.mark.asyncio
    async def test_cleanup_failure_is_swallowed_original_error_reraises(self) -> None:
        """Cleanup delete raising must not mask the original create error."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

        cfg = ConfigCloudHetzner(token="test-cleanup-fail")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAA test"

        ssh_keys_empty = _make_mock_resp(200, _ssh_keys_list_empty())
        ssh_key_create = _make_mock_resp(201, _ssh_key_create(1))
        create_resp = _make_mock_resp(
            201,
            {"server": {"id": 55, "public_net": None}},
        )
        # Cleanup DELETE itself fails with 403 — swallowed by _best_effort_delete.
        delete_resp = _make_mock_resp(403, _hetz_err("forbidden", "forbidden", 403))
        session = _make_mock_session_with_queue(
            [ssh_keys_empty, ssh_key_create, create_resp, delete_resp]
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
                return_value=session,
            ),
            patch(
                "yascheduler.infra.cloud.providers.hetzner.get_key_name",
                return_value="yakey-abc",
            ),
            pytest.raises(RuntimeError, match="without a public IPv4"),
        ):
            await hetzner_create_node(cfg, mock_key)

        assert session.request.call_count == 4

    @pytest.mark.asyncio
    async def test_happy_path_no_cleanup(
        self,
        log_records: list[logging.LogRecord],
    ) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.dto import CloudCreateNodeDTO
        from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

        cfg = ConfigCloudHetzner(token="test-happy")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAA test"

        # GET /ssh_keys empty → POST /ssh_keys → POST /servers (happy).
        ssh_keys_empty = _make_mock_resp(200, _ssh_keys_list_empty())
        ssh_key_create = _make_mock_resp(201, _ssh_key_create(1))
        create_resp = _make_mock_resp(
            201,
            {"server": {"id": 42, "public_net": {"ipv4": {"ip": "1.2.3.4"}}}},
        )
        session = _make_mock_session_with_queue(
            [ssh_keys_empty, ssh_key_create, create_resp]
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
                return_value=session,
            ),
            patch(
                "yascheduler.infra.cloud.providers.hetzner.get_key_name",
                return_value="yakey-abc",
            ),
        ):
            result = await hetzner_create_node(cfg, mock_key)

        assert isinstance(result, CloudCreateNodeDTO)
        assert result.external_id == "42"
        assert result.hostname == "1.2.3.4"
        assert session.request.call_count == 3  # no cleanup DELETE
        # CREATE_FAILED_CLEANUP must NOT be emitted on happy path.
        cleanup_records = [
            r for r in log_records if r.getMessage() == "CREATE_FAILED_CLEANUP"
        ]
        assert cleanup_records == []

    @pytest.mark.asyncio
    async def test_existing_ssh_key_skips_post(self) -> None:
        """GET /ssh_keys finds the key → POST /ssh_keys skipped → POST /servers."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

        cfg = ConfigCloudHetzner(token="test-existing-key")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAA test"

        # GET /ssh_keys finds key id=7 → POST /servers (no POST /ssh_keys).
        ssh_keys_found = _make_mock_resp(200, _ssh_keys_list(_ssh_key(key_id=7)))
        create_resp = _make_mock_resp(
            201,
            {"server": {"id": 42, "public_net": {"ipv4": {"ip": "1.2.3.4"}}}},
        )
        session = _make_mock_session_with_queue([ssh_keys_found, create_resp])

        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
                return_value=session,
            ),
            patch(
                "yascheduler.infra.cloud.providers.hetzner.get_key_name",
                return_value="yakey-abc",
            ),
        ):
            result = await hetzner_create_node(cfg, mock_key)

        assert result.external_id == "42"
        assert session.request.call_count == 2  # GET + POST /servers only


# =============================================================================
# hetzner_delete_node
# =============================================================================


class TestHetznerDeleteNode:
    """hetzner_delete_node() — invalid id, happy path, idempotent not_found."""

    @pytest.mark.asyncio
    async def test_invalid_external_id_raises(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import hetzner_delete_node

        cfg = ConfigCloudHetzner(token="test-invalid-id")

        # Session is never opened because id parsing fails first.
        with pytest.raises(RuntimeError, match="Invalid Hetzner server id"):
            await hetzner_delete_node(cfg, external_id="not-a-number")

    @pytest.mark.asyncio
    async def test_happy_path_delete(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import hetzner_delete_node

        cfg = ConfigCloudHetzner(token="test-del-happy")
        delete_resp = _make_mock_resp(200, {})  # DELETE success
        session = _make_mock_session_with_queue([delete_resp])

        with patch(
            "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
            return_value=session,
        ):
            await hetzner_delete_node(cfg, external_id="42")

        session.request.assert_called_once()
        call = session.request.call_args
        assert call.args[0] == "DELETE"
        assert call.args[1].endswith("/servers/42")

    @pytest.mark.asyncio
    async def test_not_found_from_delete_is_idempotent(self) -> None:
        """DELETE returning 404 not_found is a no-op, not an error."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import hetzner_delete_node

        cfg = ConfigCloudHetzner(token="test-del-404")
        delete_resp = _make_mock_resp(
            404,
            _hetz_err("not_found", "server not found", 404),
        )
        session = _make_mock_session_with_queue([delete_resp])

        with patch(
            "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
            return_value=session,
        ):
            # Should not raise.
            await hetzner_delete_node(cfg, external_id="152213839")

        session.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_permanent_4xx_raises(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import (
            HetznerError,
            hetzner_delete_node,
        )

        cfg = ConfigCloudHetzner(token="test-del-403")
        delete_resp = _make_mock_resp(
            403,
            _hetz_err("forbidden", "forbidden", 403),
        )
        session = _make_mock_session_with_queue([delete_resp])

        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
                return_value=session,
            ),
            pytest.raises(HetznerError),
        ):
            await hetzner_delete_node(cfg, external_id="42")

    @pytest.mark.asyncio
    async def test_transient_5xx_retried_then_succeeds(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import hetzner_delete_node

        cfg = ConfigCloudHetzner(token="test-del-retry")
        fail_resp = _make_mock_resp(500, _hetz_err("internal_error", "boom", 500))
        ok_resp = _make_mock_resp(200, {})  # DELETE success
        session = _make_mock_session_with_queue([fail_resp, ok_resp])

        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.aiohttp.ClientSession",
                return_value=session,
            ),
            patch(
                "yascheduler.infra.cloud.providers.hetzner.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            await hetzner_delete_node(cfg, external_id="42")

        assert session.request.call_count == 2
