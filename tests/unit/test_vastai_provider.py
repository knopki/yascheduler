"""Tests for VastAI provider module."""
# region MODULE_CONTRACT
# PURPOSE: Unit tests for VastAI provider: exception hierarchy, public function
#          stubs, HTTP helpers.
# SCOPE: vastai.py module-level behavior; HTTP helpers via mocked session.
# KEYWORDS: vastai, provider, unit, exceptions, http
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from yascheduler.shared.log import _NATIVE_KEYS


class LogCaptureHandler(logging.Handler):
    """Capture log records for assertion."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)


@pytest.fixture
def log_records() -> Generator[list[logging.LogRecord], None, None]:
    """Capture log records from the vastai provider logger."""
    logger = logging.getLogger("yascheduler.infra.cloud.providers.vastai")
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


def extra_fields(record: logging.LogRecord) -> dict[str, object]:
    """Reconstruct structured fields from a log record."""
    return {k: getattr(record, k) for k in record.__dict__ if k not in _NATIVE_KEYS}


class TestExceptionHierarchy:
    """VastAI exception hierarchy: subclass relationships and free-form message."""

    def test_vastai_error_is_exception(self) -> None:
        """VastAIError subclasses Exception."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError

        assert issubclass(VastAIError, Exception)

    def test_vastai_error_not_scheduling_error(self) -> None:
        """VastAIError is not a SchedulingError."""
        from yascheduler.domain.exceptions import SchedulingError
        from yascheduler.infra.cloud.providers.vastai import VastAIError

        assert not issubclass(VastAIError, SchedulingError)

    @pytest.mark.parametrize(
        "exc_cls",
        [
            "VastAIDeleteError",
            "VastAINoOffersError",
            "VastAIInvalidOfferError",
            "VastAIInstanceCreateError",
        ],
    )
    def test_exception_subclasses_vastai_error(self, exc_cls: str) -> None:
        """Each VastAI exception subclasses VastAIError."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        exc = getattr(vastai_mod, exc_cls)
        assert issubclass(exc, vastai_mod.VastAIError)

    @pytest.mark.parametrize(
        "exc_cls",
        [
            "VastAIError",
            "VastAIDeleteError",
            "VastAINoOffersError",
            "VastAIInvalidOfferError",
            "VastAIInstanceCreateError",
        ],
    )
    def test_exception_carries_free_form_message(self, exc_cls: str) -> None:
        """str(e) equals the message passed to the constructor."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        exc = getattr(vastai_mod, exc_cls)
        instance = exc("test message")
        assert str(instance) == "test message"


class TestHelperStubs:
    """Helper function stubs exist and raise NotImplementedError."""

    @pytest.mark.parametrize(
        "helper_name",
        [
            "ensure_ssh_key",
            "search_offers",
            "select_cheapest_offer",
            "generate_onstart",
            "detect_launch_mode",
            "wait_until_ready",
        ],
    )
    def test_helper_exists(self, helper_name: str) -> None:
        """Each helper function exists in the module."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        assert hasattr(vastai_mod, helper_name)

    @pytest.mark.parametrize(
        "helper_name",
        [
            "ensure_ssh_key",
            "search_offers",
            "select_cheapest_offer",
            "generate_onstart",
            "detect_launch_mode",
            "wait_until_ready",
        ],
    )
    def test_helper_not_in_all(self, helper_name: str) -> None:
        """Helper functions are not in __all__."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        assert helper_name not in vastai_mod.__all__

    @pytest.mark.parametrize(
        "helper_name",
        [
            "ensure_ssh_key",
            "search_offers",
            "select_cheapest_offer",
            "generate_onstart",
            "wait_until_ready",
        ],
    )
    def test_helper_is_async(self, helper_name: str) -> None:
        """Each helper is an async function (coroutine function)."""
        import inspect

        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        helper = getattr(vastai_mod, helper_name)
        assert inspect.iscoroutinefunction(helper)


class TestDetectLaunchMode:
    """detect_launch_mode: kvm/docker by image substring."""

    def test_kvm_when_image_contains_vastai_kvm(self) -> None:
        """Returns 'kvm' when image contains 'vastai/kvm'."""
        from yascheduler.infra.cloud.providers.vastai import detect_launch_mode

        result = detect_launch_mode("vastai/kvm:latest")
        assert result == "kvm"

    def test_docker_when_image_does_not_contain_kvm(self) -> None:
        """Returns 'docker' when image does not contain 'vastai/kvm'."""
        from yascheduler.infra.cloud.providers.vastai import detect_launch_mode

        result = detect_launch_mode("pytorch/pytorch:latest")
        assert result == "docker"


class TestGenerateOnstart:
    """generate_onstart: custom verbatim, translation with apt-get/dnf, bootcmd, KVM shebang."""

    @pytest.mark.asyncio
    async def test_custom_onstart_used_verbatim(self) -> None:
        """Non-empty cfg.onstart_script is returned verbatim."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import generate_onstart

        cfg = ConfigCloudVastAI(onstart_script="echo hello", api_key="test-key")
        result = await generate_onstart(cfg)
        assert result == "echo hello"

    @pytest.mark.asyncio
    async def test_translation_with_apt_get(self) -> None:
        """Cloud-init translation uses apt-get for Debian/Ubuntu images."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.cloud_init import CloudInitConfig
        from yascheduler.infra.cloud.providers.vastai import generate_onstart

        cfg = ConfigCloudVastAI(image="ubuntu:22.04", api_key="test-key")
        cloud_config = CloudInitConfig(
            package_upgrade=True,
            packages=["curl", "git"],
        )
        result = await generate_onstart(cfg, cloud_config)
        assert "apt-get update && apt-get upgrade -y" in result
        assert "apt-get install -y curl git" in result

    @pytest.mark.asyncio
    async def test_translation_with_dnf(self) -> None:
        """Cloud-init translation uses dnf for non-Debian/Ubuntu images."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.cloud_init import CloudInitConfig
        from yascheduler.infra.cloud.providers.vastai import generate_onstart

        cfg = ConfigCloudVastAI(image="fedora:latest", api_key="test-key")
        cloud_config = CloudInitConfig(
            package_upgrade=True,
            packages=["curl", "git"],
        )
        result = await generate_onstart(cfg, cloud_config)
        assert "dnf upgrade -y" in result
        assert "dnf install -y curl git" in result

    @pytest.mark.asyncio
    async def test_bootcmd_appended(self) -> None:
        """Bootcmd lines are appended to the generated script."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.cloud_init import CloudInitConfig
        from yascheduler.infra.cloud.providers.vastai import generate_onstart

        cfg = ConfigCloudVastAI(image="ubuntu:22.04", api_key="test-key")
        cloud_config = CloudInitConfig(
            bootcmd=(["echo hello", "echo world"],),
        )
        result = await generate_onstart(cfg, cloud_config)
        assert result == "echo hello\necho world"

    @pytest.mark.asyncio
    async def test_kvm_shebang_added(self) -> None:

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.cloud_init import CloudInitConfig
        from yascheduler.infra.cloud.providers.vastai import generate_onstart

        cfg = ConfigCloudVastAI(image="vastai/kvm:ubuntu", api_key="test-key")
        cloud_config = CloudInitConfig(
            bootcmd=(["echo hi"],),
        )
        result = await generate_onstart(cfg, cloud_config)
        assert result.startswith("#!/bin/bash")


class TestSelectCheapestOffer:
    """select_cheapest_offer: empty list, valid selection, invalid offer."""

    @pytest.mark.asyncio
    async def test_empty_list_raises_no_offers_error(self) -> None:
        """Empty offers list raises VastAINoOffersError."""
        from yascheduler.infra.cloud.providers.vastai import (
            VastAINoOffersError,
            select_cheapest_offer,
        )

        with pytest.raises(VastAINoOffersError):
            await select_cheapest_offer([], 1.0)

    @pytest.mark.asyncio
    async def test_selects_random_offer_from_top_5_cheapest(self) -> None:
        """Selects a random offer from the top-5 cheapest (avoids always hitting same provider)."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.providers.vastai import (
            VastAIOffer,
            select_cheapest_offer,
        )

        offers: list[VastAIOffer] = [
            {"id": 101, "dph_total": 0.5},
            {"id": 102, "dph_total": 0.8},
            {"id": 103, "dph_total": 0.9},
            {"id": 104, "dph_total": 1.0},
            {"id": 105, "dph_total": 1.1},
            {"id": 106, "dph_total": 2.0},
        ]
        with patch(
            "yascheduler.infra.cloud.providers.vastai.random.choice"
        ) as mock_choice:
            mock_choice.return_value = {"id": 103, "dph_total": 0.9}
            result = await select_cheapest_offer(offers, 2.0)

        # random.choice called with top-5 cheapest, sorted ascending
        (candidates,) = mock_choice.call_args[0]
        assert len(candidates) == 5
        assert candidates[0]["id"] == 101
        assert candidates[-1]["id"] == 105
        # function returns whatever random.choice returned
        assert result["id"] == 103

    @pytest.mark.asyncio
    async def test_price_over_limit_raises_invalid_offer_error(self) -> None:
        """Offer with dph_total exceeding max_price_per_hr raises VastAIInvalidOfferError."""
        from yascheduler.infra.cloud.providers.vastai import (
            VastAIInvalidOfferError,
            VastAIOffer,
            select_cheapest_offer,
        )

        offers: list[VastAIOffer] = [{"id": 101, "dph_total": 2.0}]
        with pytest.raises(VastAIInvalidOfferError):
            await select_cheapest_offer(offers, 1.0)


class TestRequest:
    """request: single HTTP entry point."""

    @pytest.mark.asyncio
    async def test_non_2xx_raises_vastai_error(self) -> None:
        """Non-2xx status raises VastAIError."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _request

        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.json = AsyncMock(return_value={"msg": "unauthorized"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        with pytest.raises(VastAIError):
            await _request(mock_session, "GET", "/test", "key")

    @pytest.mark.asyncio
    async def test_bad_json_raises_vastai_error(self) -> None:
        """Non-JSON response raises VastAIError."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _request

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(side_effect=ValueError("bad json"))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        with pytest.raises(VastAIError):
            await _request(mock_session, "GET", "/test", "key")

    @pytest.mark.asyncio
    async def test_2xx_returns_parsed_body(self) -> None:
        """2xx response returns parsed JSON body."""
        from yascheduler.infra.cloud.providers.vastai import _request

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"id": 42, "status": "ok"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        result = await _request(mock_session, "GET", "/test", "key")
        assert result == {"id": 42, "status": "ok"}

    @pytest.mark.asyncio
    async def test_api_key_absent_from_logged_fields(
        self,
        log_records: list,
    ) -> None:
        """API key does not appear in any structured log field."""
        from yascheduler.infra.cloud.providers.vastai import _request

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ok": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        await _request(mock_session, "GET", "/test", "my-secret-api-key")

        for rec in log_records:
            fields = extra_fields(rec)
            for v in fields.values():
                assert "my-secret-api-key" not in str(v)


class TestEnsureSshKey:
    """ensure_ssh_key: presence check, registration."""

    @pytest.mark.asyncio
    async def test_already_present_does_not_post(self) -> None:
        """Key already registered does not POST."""
        from yascheduler.infra.cloud.providers.vastai import ensure_ssh_key

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value=[{"public_key": "ssh-rsa AAAA..."}],
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        await ensure_ssh_key(mock_session, "ssh-rsa AAAA...")

        # Only GET was called, no POST
        calls = [c[0] for c in mock_session.request.call_args_list]
        assert len(calls) == 1
        assert calls[0][0] == "GET"

    @pytest.mark.asyncio
    async def test_absent_posts_new_key(self) -> None:
        """Key not registered sends POST."""
        from yascheduler.infra.cloud.providers.vastai import ensure_ssh_key

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=[])
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        await ensure_ssh_key(mock_session, "ssh-rsa AAAA...")

        calls = [c[0] for c in mock_session.request.call_args_list]
        assert len(calls) == 2
        assert calls[0][0] == "GET"
        assert calls[1][0] == "POST"


class TestSearchOffers:
    """search_offers: posts expected filter body, returns offers."""

    @pytest.mark.asyncio
    async def test_posts_expected_filter_and_returns_offers(self) -> None:
        """Posts the expected filter body and returns offers list."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import search_offers

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"offers": [{"id": 101, "dph_total": 0.5}]},
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        cfg = ConfigCloudVastAI(
            min_vram_mb=16384,
            num_gpus=1,
            max_price_per_hr=1.0,
            api_key="test-key",
        )

        offers = await search_offers(mock_session, cfg)
        assert offers == [{"id": 101, "dph_total": 0.5}]

        # Verify the POST body
        call_kwargs = mock_session.request.call_args.kwargs
        assert call_kwargs.get("json") is not None
        body = call_kwargs["json"]
        assert body["duration"]["gte"] == 60
        assert body["gpu_ram"]["gte"] == 16384
        assert body["num_gpus"]["eq"] == 1
        assert body["gpu_frac"]["gte"] == 1.0
        assert body["rentable"]["eq"] is True
        assert body["rented"]["eq"] is False
        assert body["dph_total"]["lte"] == 1.0
        assert body["type"] == "on-demand"
        assert body["order"] == [["dph_total", "asc"]]
        assert body["limit"] == 20


class TestWaitUntilReady:
    """wait_until_ready: polling, timeout, terminal status."""

    @pytest.mark.asyncio
    async def test_ready_returns_instance(self) -> None:
        """Ready instance returns the instance dict."""
        from yascheduler.infra.cloud.providers.vastai import wait_until_ready

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "instances": {
                    "id": 42,
                    "actual_status": "running",
                    "ssh_host": "1.2.3.4",
                    "ssh_port": 2222,
                },
            },
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        result = await wait_until_ready(mock_session, 42, 300.0)
        assert result["id"] == 42
        assert result["ssh_host"] == "1.2.3.4"
        assert result["ssh_port"] == 2222

    @pytest.mark.asyncio
    async def test_timeout_raises_and_deletes(self) -> None:
        """Timeout raises VastAIInstanceCreateError and best-effort DELETEs."""
        from yascheduler.infra.cloud.providers.vastai import (
            VastAIInstanceCreateError,
            wait_until_ready,
        )

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "instances": {
                    "id": 42,
                    "actual_status": "created",
                    "ssh_host": "",
                    "ssh_port": 0,
                },
            },
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        with pytest.raises(VastAIInstanceCreateError):
            await wait_until_ready(mock_session, 42, 0.0)

        # Should have attempted DELETE
        delete_calls = [
            c for c in mock_session.request.call_args_list if c[0][0] == "DELETE"
        ]
        assert len(delete_calls) >= 1

    @pytest.mark.parametrize("terminal_status", ["exited", "unknown", "offline"])
    @pytest.mark.asyncio
    async def test_terminal_status_raises_and_deletes(
        self,
        terminal_status: str,
    ) -> None:
        """Terminal status raises VastAIInstanceCreateError and best-effort DELETEs."""
        from yascheduler.infra.cloud.providers.vastai import (
            VastAIInstanceCreateError,
            wait_until_ready,
        )

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "instances": {
                    "id": 42,
                    "actual_status": terminal_status,
                    "ssh_host": "",
                    "ssh_port": 0,
                },
            },
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)

        with pytest.raises(VastAIInstanceCreateError):
            await wait_until_ready(mock_session, 42, 300.0)

        # Should have attempted DELETE
        delete_calls = [
            c for c in mock_session.request.call_args_list if c[0][0] == "DELETE"
        ]
        assert len(delete_calls) >= 1


class TestVastaiCreateNode:
    """vastai_create_node: full orchestration with mocked session."""

    @pytest.mark.asyncio
    async def test_returns_dto_with_correct_fields(self) -> None:
        """Returns CloudCreateNodeDTO with external_id=instance_id, hostname=ssh_host, port=ssh_port."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_create_node

        cfg = ConfigCloudVastAI(
            api_key="test-key",
            jump_host="jump.example.com",
            jump_port=2222,
            jump_username="jumpuser",
        )
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAA..."

        def make_mock_resp(status: int, json_data: object) -> MagicMock:
            mock_resp = MagicMock()
            mock_resp.status = status
            mock_resp.json = AsyncMock(return_value=json_data)
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)
            return mock_resp

        # 1. GET /ssh/ → key already present
        resp1 = make_mock_resp(200, [{"public_key": "ssh-rsa AAAA..."}])
        # 2. POST /bundles/ → offers
        resp2 = make_mock_resp(200, {"offers": [{"id": 101, "dph_total": 0.5}]})
        # 3. PUT /asks/101/ → instance created
        resp3 = make_mock_resp(200, {"new_contract": 42})
        # 4. GET /instances/42/ → ready
        resp4 = make_mock_resp(
            200,
            {
                "instances": {
                    "id": 42,
                    "actual_status": "running",
                    "ssh_host": "1.2.3.4",
                    "ssh_port": 2222,
                },
            },
        )

        mock_session = MagicMock()
        mock_session.request = MagicMock(side_effect=[resp1, resp2, resp3, resp4])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await vastai_create_node(cfg, mock_key)

        assert result.external_id == "42"
        assert result.hostname == "1.2.3.4"
        assert result.port == 2222  # ssh_port from instance readiness
        assert result.username == "root"
        assert result.jump_host == "jump.example.com"
        assert result.jump_port == 2222
        assert result.jump_username == "jumpuser"

    @pytest.mark.asyncio
    async def test_emits_block_markers_in_order(
        self,
        log_records: list,
    ) -> None:
        """Emits block markers: SSH_KEY_CHECK, OFFER_SEARCH_START, OFFER_SELECT, INSTANCE_CREATE, INSTANCE_READY."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_create_node

        cfg = ConfigCloudVastAI(api_key="test-key")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAA..."

        def make_mock_resp(status: int, json_data: object) -> MagicMock:
            mock_resp = MagicMock()
            mock_resp.status = status
            mock_resp.json = AsyncMock(return_value=json_data)
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)
            return mock_resp

        resp1 = make_mock_resp(200, [{"public_key": "ssh-rsa AAAA..."}])
        resp2 = make_mock_resp(200, {"offers": [{"id": 101, "dph_total": 0.5}]})
        resp3 = make_mock_resp(200, {"new_contract": 42})
        resp4 = make_mock_resp(
            200,
            {
                "instances": {
                    "id": 42,
                    "actual_status": "running",
                    "ssh_host": "1.2.3.4",
                    "ssh_port": 2222,
                },
            },
        )

        mock_session = MagicMock()
        mock_session.request = MagicMock(side_effect=[resp1, resp2, resp3, resp4])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            await vastai_create_node(cfg, mock_key)

        markers = [r.getMessage() for r in log_records]
        expected_order = [
            "SSH_KEY_CHECK",
            "OFFER_SEARCH_START",
            "OFFER_SELECT",
            "INSTANCE_CREATE",
            "INSTANCE_READY",
        ]
        # Each expected marker must appear in order
        idx = 0
        for marker in expected_order:
            assert marker in markers[idx:], f"Missing marker: {marker}"
            idx = markers.index(marker, idx) + 1


class TestVastaiDeleteNode:
    """vastai_delete_node: delete with mocked session."""

    @pytest.mark.asyncio
    async def test_issues_delete_and_returns_none(self) -> None:
        """Issues DELETE /instances/{external_id}/ and returns None."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_delete_node

        cfg = ConfigCloudVastAI(api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"success": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            await vastai_delete_node(cfg, "42")

        # Verify DELETE was called with the correct path
        call_args = mock_session.request.call_args
        assert call_args[0][0] == "DELETE"
        assert "/instances/42/" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_404_returns_none_idempotent(self) -> None:
        """404 response returns None (idempotent delete)."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_delete_node

        cfg = ConfigCloudVastAI(api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_resp.json = AsyncMock(return_value={"msg": "not found"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            await vastai_delete_node(cfg, "42")


class TestVastaiDeleteNodeNon2xx:
    """vastai_delete_node: non-2xx error handling."""

    @pytest.mark.asyncio
    async def test_non_2xx_non_404_raises_delete_error(self) -> None:
        """Non-2xx non-404 response raises VastAIDeleteError.

        Uses 403 (forbidden): non-retryable, so the error surfaces without
        retry delay. A 500 would be retried (idempotent DELETE) and require
        sleep mocking; that path is covered separately.
        """
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import (
            VastAIDeleteError,
            vastai_delete_node,
        )

        cfg = ConfigCloudVastAI(api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.status = 403
        mock_resp.json = AsyncMock(return_value={"msg": "forbidden"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
                return_value=mock_session,
            ),
            pytest.raises(VastAIDeleteError),
        ):
            await vastai_delete_node(cfg, "42")

    @pytest.mark.asyncio
    async def test_5xx_retries_then_raises_delete_error(self) -> None:
        """5xx on DELETE is retried; persistent 5xx surfaces as VastAIDeleteError."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        cfg = ConfigCloudVastAI(api_key="test-key")

        def make_resp(status: int, body: dict) -> MagicMock:
            mock_resp = MagicMock()
            mock_resp.status = status
            mock_resp.json = AsyncMock(return_value=body)
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)
            return mock_resp

        # Fail a few times, then succeed — proves 5xx is retried on DELETE.
        mock_session = MagicMock()
        mock_session.request = MagicMock(
            side_effect=[
                make_resp(503, {"msg": "unavailable"}),
                make_resp(502, {"msg": "bad gateway"}),
                make_resp(200, {"success": True}),
            ],
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(vastai_mod.asyncio, "sleep", new=AsyncMock()),
            patch(
                "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
                return_value=mock_session,
            ),
        ):
            await vastai_mod.vastai_delete_node(cfg, "42")

        # Retried twice before succeeding.
        assert mock_session.request.call_count == 3


class TestVastaiCreateNodeApiKeyRedaction:
    """vastai_create_node: api_key redaction from log fields."""

    @pytest.mark.asyncio
    async def test_api_key_absent_from_logged_fields(
        self,
        log_records: list,
    ) -> None:
        """API key does not appear in any structured log field during create_node."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_create_node

        cfg = ConfigCloudVastAI(api_key="my-secret-api-key-12345")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAA..."

        def make_mock_resp(status: int, json_data: object) -> MagicMock:
            mock_resp = MagicMock()
            mock_resp.status = status
            mock_resp.json = AsyncMock(return_value=json_data)
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)
            return mock_resp

        resp1 = make_mock_resp(200, [{"public_key": "ssh-rsa AAAA..."}])
        resp2 = make_mock_resp(200, {"offers": [{"id": 101, "dph_total": 0.5}]})
        resp3 = make_mock_resp(200, {"new_contract": 42})
        resp4 = make_mock_resp(
            200,
            {
                "instances": {
                    "id": 42,
                    "actual_status": "running",
                    "ssh_host": "1.2.3.4",
                    "ssh_port": 2222,
                },
            },
        )

        mock_session = MagicMock()
        mock_session.request = MagicMock(side_effect=[resp1, resp2, resp3, resp4])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            await vastai_create_node(cfg, mock_key)

        for rec in log_records:
            fields = extra_fields(rec)
            for v in fields.values():
                assert "my-secret-api-key-12345" not in str(v)


class TestVastaiListInstances:
    """vastai_list_instances: list and filter by label."""

    @pytest.mark.asyncio
    async def test_returns_yascheduler_instances_only(self) -> None:
        """Returns only instances with label='yascheduler'."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_list_instances

        cfg = ConfigCloudVastAI(api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "instances": [
                    {"id": 1, "label": "yascheduler", "actual_status": "running"},
                    {"id": 2, "label": "other", "actual_status": "running"},
                    {"id": 3, "label": "yascheduler", "actual_status": "stopped"},
                ],
            },
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await vastai_list_instances(cfg)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 3

    @pytest.mark.asyncio
    async def test_empty_when_no_yascheduler_instances(self) -> None:
        """Returns empty list when no instances have label='yascheduler'."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_list_instances

        cfg = ConfigCloudVastAI(api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "instances": [
                    {"id": 1, "label": "other", "actual_status": "running"},
                ],
            },
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await vastai_list_instances(cfg)

        assert result == []

    @pytest.mark.asyncio
    async def test_empty_when_response_missing_instances_key(self) -> None:
        """Returns empty list when API response lacks 'instances' key."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_list_instances

        cfg = ConfigCloudVastAI(api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"success": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await vastai_list_instances(cfg)

        assert result == []

    @pytest.mark.asyncio
    async def test_empty_when_instances_not_list(self) -> None:
        """Returns empty list when instances field is not a list."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_list_instances

        cfg = ConfigCloudVastAI(api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"instances": {}})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await vastai_list_instances(cfg)

        assert result == []

    @pytest.mark.asyncio
    async def test_emits_list_instances_log(self, log_records: list) -> None:
        """Emits LIST_INSTANCES block marker with total and yascheduler counts."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_list_instances

        cfg = ConfigCloudVastAI(api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "instances": [
                    {"id": 1, "label": "yascheduler", "actual_status": "running"},
                    {"id": 2, "label": "other", "actual_status": "running"},
                ],
            },
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            await vastai_list_instances(cfg)

        list_records = [r for r in log_records if r.getMessage() == "LIST_INSTANCES"]
        assert len(list_records) == 1
        fields = extra_fields(list_records[0])
        assert fields.get("total") == 2
        assert fields.get("matched") == 1
        assert fields.get("label") == "yascheduler"

    @pytest.mark.asyncio
    async def test_custom_label_filter(self) -> None:
        """Returns only instances matching a custom cfg.label."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers.vastai import vastai_list_instances

        cfg = ConfigCloudVastAI(api_key="test-key", label="yascheduler-e2e-test")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "instances": [
                    {"id": 1, "label": "yascheduler", "actual_status": "running"},
                    {
                        "id": 2,
                        "label": "yascheduler-e2e-test",
                        "actual_status": "running",
                    },
                    {"id": 3, "label": "other", "actual_status": "stopped"},
                ],
            },
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await vastai_list_instances(cfg)

        assert len(result) == 1
        assert result[0]["id"] == 2


class TestRequestTransportErrors:
    """_request wraps transport errors into VastAIError(status=None)."""

    @pytest.mark.asyncio
    async def test_client_error_wrapped_status_none(self) -> None:
        """aiohttp.ClientError from the session is wrapped into VastAIError(status=None)."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _request

        mock_session = MagicMock()
        mock_session.request = MagicMock(
            side_effect=aiohttp.ClientConnectionError("connection refused"),
        )

        with pytest.raises(VastAIError) as exc_info:
            await _request(mock_session, "GET", "/test")

        assert exc_info.value.status is None

    @pytest.mark.asyncio
    async def test_timeout_error_wrapped_status_none(self) -> None:
        """asyncio.TimeoutError is wrapped into VastAIError(status=None)."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _request

        mock_session = MagicMock()
        mock_session.request = MagicMock(side_effect=asyncio.TimeoutError())

        with pytest.raises(VastAIError) as exc_info:
            await _request(mock_session, "GET", "/test")

        assert exc_info.value.status is None


class TestIsRetryable:
    """_is_retryable: method-aware retry decision guarding against double-create."""

    @pytest.mark.parametrize("method", ["GET", "HEAD", "DELETE", "OPTIONS", "get"])
    def test_idempotent_transport_retryable(self, method: str) -> None:
        """Transport error (status None) is retryable for idempotent methods."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _is_retryable

        assert _is_retryable(method, VastAIError("net", status=None))

    @pytest.mark.parametrize("method", ["GET", "DELETE"])
    def test_idempotent_5xx_retryable(self, method: str) -> None:
        """5xx is retryable for idempotent methods."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _is_retryable

        assert _is_retryable(method, VastAIError("boom", status=500))
        assert _is_retryable(method, VastAIError("boom", status=503))

    @pytest.mark.parametrize("method", ["GET", "PUT", "POST", "DELETE"])
    def test_429_always_retryable(self, method: str) -> None:
        """429 is retryable for every method (rate-limited = not executed)."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _is_retryable

        assert _is_retryable(method, VastAIError("slow down", status=429))

    @pytest.mark.parametrize("method", ["PUT", "POST"])
    def test_mutating_transport_not_retryable(self, method: str) -> None:
        """Transport error is NOT retried for mutating methods — no double-create."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _is_retryable

        assert not _is_retryable(method, VastAIError("net", status=None))

    @pytest.mark.parametrize("method", ["PUT", "POST"])
    def test_mutating_5xx_not_retryable(self, method: str) -> None:
        """5xx is NOT retried for mutating methods — create may have executed."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _is_retryable

        assert not _is_retryable(method, VastAIError("boom", status=500))

    def test_4xx_not_retryable(self) -> None:
        """4xx (non-429) is not retryable."""
        from yascheduler.infra.cloud.providers.vastai import VastAIError, _is_retryable

        assert not _is_retryable("GET", VastAIError("bad", status=400))
        assert not _is_retryable("DELETE", VastAIError("forbidden", status=403))


class TestRequestWithRetryIntegration:
    """_request_with_retry: retry behavior with mocked transport and HTTP errors."""

    def _resp(self, status: int, body: object) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=body)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    @pytest.mark.asyncio
    async def test_get_transport_then_success_retries(self) -> None:
        """GET: transient transport error is retried and succeeds on 2nd attempt."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        mock_session = MagicMock()
        mock_session.request = MagicMock(
            side_effect=[
                aiohttp.ClientConnectionError("flap"),
                self._resp(200, {"ok": True}),
            ],
        )

        with patch.object(vastai_mod.asyncio, "sleep", new=AsyncMock()):
            data = await vastai_mod._request_with_retry(
                mock_session,
                "GET",
                "/x",
            )

        assert data == {"ok": True}
        assert mock_session.request.call_count == 2

    @pytest.mark.asyncio
    async def test_put_transport_not_retried(self) -> None:
        """PUT (create): transport error NOT retried — prevents double-create."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        mock_session = MagicMock()
        mock_session.request = MagicMock(
            side_effect=aiohttp.ClientConnectionError("flap"),
        )

        with (
            patch.object(vastai_mod.asyncio, "sleep", new=AsyncMock()),
            pytest.raises(vastai_mod.VastAIError) as exc_info,
        ):
            await vastai_mod._request_with_retry(mock_session, "PUT", "/asks/1/")

        # Called exactly once: the non-idempotent PUT must not be retried on an
        # uncertain transport outcome (the server may have created the instance).
        assert mock_session.request.call_count == 1
        assert exc_info.value.status is None

    @pytest.mark.asyncio
    async def test_delete_5xx_then_success_retries(self) -> None:
        """DELETE: transient 503 is retried and succeeds."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        mock_session = MagicMock()
        mock_session.request = MagicMock(
            side_effect=[
                self._resp(503, {"msg": "unavailable"}),
                self._resp(200, {"success": True}),
            ],
        )

        with patch.object(vastai_mod.asyncio, "sleep", new=AsyncMock()):
            data = await vastai_mod._request_with_retry(
                mock_session,
                "DELETE",
                "/instances/1/",
            )

        assert data == {"success": True}
        assert mock_session.request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_4xx_not_retried(self) -> None:
        """GET 400 is not retryable — single attempt, raises."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        mock_session = MagicMock()
        mock_session.request = MagicMock(
            return_value=self._resp(400, {"msg": "bad request"}),
        )

        with (
            patch.object(vastai_mod.asyncio, "sleep", new=AsyncMock()),
            pytest.raises(vastai_mod.VastAIError),
        ):
            await vastai_mod._request_with_retry(mock_session, "GET", "/x")

        assert mock_session.request.call_count == 1


class TestBestEffortDelete:
    """_best_effort_delete swallows any exception so cleanup never masks the original error."""

    @pytest.mark.asyncio
    async def test_swallows_non_vastai_error(self) -> None:
        """An unexpected exception during cleanup is swallowed, not propagated."""
        from yascheduler.infra.cloud.providers.vastai import _best_effort_delete

        mock_session = MagicMock()
        mock_session.request = MagicMock(side_effect=RuntimeError("boom"))

        # Must not raise — best-effort cleanup must never mask the caller's error.
        await _best_effort_delete(mock_session, 42)

    @pytest.mark.asyncio
    async def test_swallows_transport_error(self) -> None:
        """A transport error during cleanup is swallowed after retry exhaustion."""
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        mock_session = MagicMock()
        mock_session.request = MagicMock(
            side_effect=aiohttp.ClientConnectionError("down"),
        )

        with patch.object(vastai_mod, "_RETRY_MAX_TIME", 0.0):
            # Must not raise.
            await vastai_mod._best_effort_delete(mock_session, 42)


class TestDeleteNodeTransportRobustness:
    """vastai_delete_node: transient transport errors are retried; persistent ones wrap into VastAIDeleteError."""

    def _resp(self, status: int, body: object) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=body)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    @pytest.mark.asyncio
    async def test_transient_transport_retried_then_succeeds(self) -> None:
        """A flapping connection is retried and the delete succeeds."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        cfg = ConfigCloudVastAI(api_key="k")

        mock_session = MagicMock()
        mock_session.request = MagicMock(
            side_effect=[
                aiohttp.ClientConnectionError("flap"),
                self._resp(200, {"success": True}),
            ],
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(vastai_mod.asyncio, "sleep", new=AsyncMock()),
            patch(
                "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
                return_value=mock_session,
            ),
        ):
            await vastai_mod.vastai_delete_node(cfg, "42")

        assert mock_session.request.call_count == 2

    @pytest.mark.asyncio
    async def test_persistent_transport_wrapped_into_delete_error(self) -> None:
        """A persistent transport error surfaces as VastAIDeleteError, not a raw aiohttp exception."""
        from unittest.mock import patch

        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI
        from yascheduler.infra.cloud.providers import vastai as vastai_mod

        cfg = ConfigCloudVastAI(api_key="k")

        mock_session = MagicMock()
        mock_session.request = MagicMock(
            side_effect=aiohttp.ClientConnectionError("down"),
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(vastai_mod, "_RETRY_MAX_TIME", 0.0),
            patch(
                "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
                return_value=mock_session,
            ),
            pytest.raises(vastai_mod.VastAIDeleteError),
        ):
            await vastai_mod.vastai_delete_node(cfg, "42")
