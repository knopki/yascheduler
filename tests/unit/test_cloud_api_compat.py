# FILE: tests/unit/test_cloud_api_compat.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Characterization tests for CloudAPI — verify old create_node/delete_node behavior preserved.
#   SCOPE: CloudAPI.create_node happy path, adapter error wrapping, setup failure cleanup, delete_node delegation.
#   DEPENDS: M-CLOUD-API
#   LINKS: M-CLOUD-API
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestCloudAPICreateNode - create_node() happy path, error wrapping, setup failure cleanup
#   TestCloudAPIDeleteNode - delete_node() delegation
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial characterization tests for CloudAPI compat.
# END_CHANGE_SUMMARY

"""Characterization tests: CloudAPI preserves old create_node behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.clouds.cloud_api import (
    CloudAPI,
    CloudCreateNodeError,
    CloudSetupNodeError,
)


def _make_cloud_api(**overrides: object) -> CloudAPI:
    """Build CloudAPI with mocked dependencies.

    All fields get sensible MagicMock defaults; pass overrides to swap any.
    """
    adapter = MagicMock()
    adapter.name = "test-cloud"
    adapter.supported_platform_checks = ()
    adapter.create_node = AsyncMock()
    adapter.delete_node = AsyncMock()
    # Return a new semaphore per call to avoid deadlock when delete_node
    # is called from within create_node's semaphore context.
    adapter.get_op_semaphore = MagicMock(side_effect=lambda: asyncio.Semaphore(1))
    adapter.create_node_conn_timeout = 10
    adapter.create_node_timeout = 300

    config = MagicMock()
    config.username = "root"

    local_config = MagicMock()
    local_config.keys_dir = MagicMock()
    local_config.keys_dir.iterdir.return_value = []
    local_config.get_private_keys.return_value = []

    remote_config = MagicMock()
    remote_config.data_dir = "."
    remote_config.engines_dir = "engines"
    remote_config.tasks_dir = "tasks"

    engines = MagicMock()
    log = MagicMock()

    kwargs: dict[str, object] = dict(
        adapter=adapter,
        config=config,
        local_config=local_config,
        remote_config=remote_config,
        engines=engines,
        log=log,
    )
    kwargs.update(overrides)
    return CloudAPI(**kwargs)  # type: ignore[arg-type,type-var]


class TestCloudAPICreateNode:
    """create_node() preserves old behavior."""

    @pytest.mark.asyncio
    async def test_create_node_returns_ip(self) -> None:
        """Happy path: create_node returns IP after successful setup."""
        api = _make_cloud_api()
        mock_machine = AsyncMock()
        mock_key = MagicMock()
        mock_cloud_config = MagicMock()

        api.adapter.create_node = AsyncMock(return_value="10.0.0.1")  # type: ignore[misc]

        mock_mk_machine = AsyncMock(return_value=mock_machine)
        # Use class-level patch (not patch.object) because CloudAPI is frozen
        mk_machine_target = "yascheduler.clouds.cloud_api.CloudAPI.mk_machine"
        get_ssh_key_target = "yascheduler.clouds.cloud_api.CloudAPI.get_ssh_key"
        get_cloud_config_target = (
            "yascheduler.clouds.cloud_api.CloudAPI.get_cloud_config_data"
        )
        with (
            patch(mk_machine_target, mock_mk_machine),
            patch(get_ssh_key_target, AsyncMock(return_value=mock_key)),
            patch(get_cloud_config_target, AsyncMock(return_value=mock_cloud_config)),
        ):
            result = await api.create_node()

        assert result == "10.0.0.1"
        api.adapter.create_node.assert_awaited_once_with(  # type: ignore[attr-defined]
            log=api.log,
            cfg=api.config,
            key=mock_key,
            cloud_config=mock_cloud_config,
        )
        mock_mk_machine.assert_awaited_once_with("10.0.0.1")
        mock_machine.run.assert_awaited_once_with("cloud-init status --wait")
        mock_machine.setup_node.assert_awaited_once_with(api.engines)

    @pytest.mark.asyncio
    async def test_create_node_wraps_create_error(self) -> None:
        """create_node raises CloudCreateNodeError when adapter.create_node fails."""
        api = _make_cloud_api()
        api.adapter.create_node = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[misc]

        get_ssh_key_target = "yascheduler.clouds.cloud_api.CloudAPI.get_ssh_key"
        get_cloud_config_target = (
            "yascheduler.clouds.cloud_api.CloudAPI.get_cloud_config_data"
        )
        with (
            patch(get_ssh_key_target, AsyncMock()),
            patch(get_cloud_config_target, AsyncMock()),
        ):
            with pytest.raises(CloudCreateNodeError, match="Create node error: boom"):
                await api.create_node()

    @pytest.mark.asyncio
    async def test_create_node_setup_failure_deletes_and_raises(self) -> None:
        """create_node deallocates and raises CloudSetupNodeError when setup fails."""
        api = _make_cloud_api()
        mock_machine = AsyncMock()
        api.adapter.create_node = AsyncMock(return_value="10.0.0.1")  # type: ignore[misc]
        api.adapter.delete_node = AsyncMock()  # type: ignore[misc]

        mock_machine.run = AsyncMock(side_effect=RuntimeError("setup boom"))

        mk_machine_target = "yascheduler.clouds.cloud_api.CloudAPI.mk_machine"
        get_ssh_key_target = "yascheduler.clouds.cloud_api.CloudAPI.get_ssh_key"
        get_cloud_config_target = (
            "yascheduler.clouds.cloud_api.CloudAPI.get_cloud_config_data"
        )
        with (
            patch(mk_machine_target, AsyncMock(return_value=mock_machine)),
            patch(get_ssh_key_target, AsyncMock()),
            patch(get_cloud_config_target, AsyncMock()),
        ):
            with pytest.raises(
                CloudSetupNodeError, match="Setup node error: setup boom"
            ):
                await api.create_node()

        api.adapter.delete_node.assert_awaited_once_with(  # type: ignore[attr-defined]
            log=api.log,
            cfg=api.config,
            host="10.0.0.1",
        )


class TestCloudAPIDeleteNode:
    """delete_node() preserves old behavior."""

    @pytest.mark.asyncio
    async def test_delete_node_delegates(self) -> None:
        """delete_node delegates to adapter.delete_node with correct args."""
        api = _make_cloud_api()
        api.adapter.delete_node = AsyncMock()  # type: ignore[misc]

        await api.delete_node("10.0.0.1")

        api.adapter.delete_node.assert_awaited_once_with(  # type: ignore[attr-defined]
            log=api.log,
            cfg=api.config,
            host="10.0.0.1",
        )
