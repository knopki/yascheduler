# FILE: tests/unit/test_cloud_api_manager.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Characterization tests for CloudAPIManager — verify old behavior preserved.
#   SCOPE: CloudAPIManager create, bool, allocate/deallocate delegation, apis compat, stop.
#   DEPENDS: M-CLOUD-MANAGER, M-CLOUD-PROVISIONER
#   LINKS: M-CLOUD-MANAGER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestCloudAPIManagerCreate - create() factory with/without adapters
#   TestCloudAPIManagerBool - __bool__ delegation
#   TestCloudAPIManagerAllocate - allocate() delegates to impl.allocate_with_tracking
#   TestCloudAPIManagerAllocateNode - allocate_node() delegates to impl.allocate_with_tracking
#   TestCloudAPIManagerDeallocate - deallocate() success/error paths
#   TestCloudAPIManagerMarkTaskDone - mark_task_done() delegation
#   TestCloudAPIManagerGetCapacity - get_capacity() returns CloudCapacity dict
#   TestCloudAPIManagerApis - apis property returns compat objects
#   TestCloudAPIManagerStop - stop() delegation
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial characterization tests for CloudAPIManager.
# END_CHANGE_SUMMARY

"""Characterization tests: CloudAPIManager preserves old behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.adapters.cloud.manager import CloudProvisionerImpl
from yascheduler.clouds.cloud_api_manager import (
    CloudAPIManager,
    _CloudAPICompat,
)


class TestCloudAPIManagerCreate:
    """CloudAPIManager.create() factory."""

    @pytest.mark.asyncio
    async def test_create_with_adapters(self) -> None:
        """create() builds CloudAPIManager wrapping CloudProvisionerImpl."""
        mock_db = MagicMock()
        mock_db._node_repo = MagicMock()
        mock_local = MagicMock()
        mock_remote = MagicMock()
        mock_engines = MagicMock()

        cfg = MagicMock()
        cfg.prefix = "az"
        cfg.max_nodes = 5

        with (
            patch(
                "yascheduler.clouds.cloud_api_manager._resolve_adapter"
            ) as mock_resolve,
            patch("yascheduler.adapters.ssh.gateway.SSHMachineGateway"),
        ):
            mock_adapter = MagicMock()
            mock_adapter.name = "az-test"
            mock_resolve.return_value = mock_adapter

            mgr = await CloudAPIManager.create(
                db=mock_db,
                local_config=mock_local,
                remote_config=mock_remote,
                cloud_configs=[cfg],
                engines=mock_engines,
            )

        assert isinstance(mgr, CloudAPIManager)
        assert bool(mgr) is True
        assert "az-test" in mgr.apis

    @pytest.mark.asyncio
    async def test_create_without_adapters(self) -> None:
        """create() returns manager with no adapters when none resolved."""
        mock_db = MagicMock()
        mock_db._node_repo = MagicMock()
        mock_local = MagicMock()
        mock_remote = MagicMock()
        mock_engines = MagicMock()

        cfg = MagicMock()
        cfg.prefix = "az"
        cfg.max_nodes = 5

        with (
            patch(
                "yascheduler.clouds.cloud_api_manager._resolve_adapter",
                return_value=None,
            ),
            patch("yascheduler.adapters.ssh.gateway.SSHMachineGateway"),
        ):
            mgr = await CloudAPIManager.create(
                db=mock_db,
                local_config=mock_local,
                remote_config=mock_remote,
                cloud_configs=[cfg],
                engines=mock_engines,
            )

        assert bool(mgr) is False
        assert mgr.apis == {}


class TestCloudAPIManagerBool:
    """__bool__ reflects adapter presence."""

    def test_true_when_adapters_present(self) -> None:
        mgr = CloudAPIManager(
            impl=MagicMock(), apis_compat={"test": MagicMock()}, log=MagicMock()
        )
        assert bool(mgr) is True

    def test_false_when_no_adapters(self) -> None:
        impl = CloudProvisionerImpl(
            adapters={},
            configs={},
            node_repo=MagicMock(),
            machine_gateway=MagicMock(),
            local_config=MagicMock(),
            remote_config=MagicMock(),
            engines=MagicMock(),
            log=MagicMock(),
        )
        mgr = CloudAPIManager(impl=impl, apis_compat={}, log=MagicMock())
        assert bool(mgr) is False


class TestCloudAPIManagerAllocate:
    """allocate() delegates to impl.allocate_with_tracking()."""

    @pytest.mark.asyncio
    async def test_delegates_to_impl(self) -> None:
        impl = MagicMock()
        impl.allocate_with_tracking = AsyncMock(return_value="10.0.0.1")
        mgr = CloudAPIManager(impl=impl, apis_compat={}, log=MagicMock())

        result = await mgr.allocate(on_task=42, want_platforms=["linux"])

        assert result == "10.0.0.1"
        impl.allocate_with_tracking.assert_awaited_once_with(
            on_task=42, platforms=["linux"], throttle=True
        )


class TestCloudAPIManagerAllocateNode:
    """allocate_node() delegates to impl.allocate_with_tracking()."""

    @pytest.mark.asyncio
    async def test_delegates_to_impl(self) -> None:
        impl = MagicMock()
        impl.allocate_with_tracking = AsyncMock(return_value="10.0.0.1")
        mgr = CloudAPIManager(impl=impl, apis_compat={}, log=MagicMock())

        result = await mgr.allocate_node(want_platforms=["linux"], throttle=True)

        assert result == "10.0.0.1"
        impl.allocate_with_tracking.assert_awaited_once_with(
            on_task=None, platforms=["linux"], throttle=True
        )


class TestCloudAPIManagerDeallocate:
    """deallocate() delegates to impl.deallocate() with error wrapping."""

    @pytest.mark.asyncio
    async def test_success_returns_none(self) -> None:
        impl = MagicMock()
        impl.deallocate = AsyncMock()
        mgr = CloudAPIManager(impl=impl, apis_compat={}, log=MagicMock())

        result = await mgr.deallocate("10.0.0.1")

        assert result is None
        impl.deallocate.assert_awaited_once_with("10.0.0.1")

    @pytest.mark.asyncio
    async def test_error_returns_false_and_logs(self) -> None:
        impl = MagicMock()
        impl.deallocate = AsyncMock(side_effect=RuntimeError("fail"))
        log = MagicMock()
        mgr = CloudAPIManager(impl=impl, apis_compat={}, log=log)

        result = await mgr.deallocate("10.0.0.1")

        assert result is False
        log.error.assert_called_once()


class TestCloudAPIManagerMarkTaskDone:
    """mark_task_done() delegates to impl.mark_task_done()."""

    def test_delegates_to_impl(self) -> None:
        impl = MagicMock()
        mgr = CloudAPIManager(impl=impl, apis_compat={}, log=MagicMock())

        mgr.mark_task_done(42)

        impl.mark_task_done.assert_called_once_with(42)


class TestCloudAPIManagerGetCapacity:
    """get_capacity() returns dict[str, CloudCapacity]."""

    @pytest.mark.asyncio
    async def test_returns_cloud_capacity_dict(self) -> None:
        from yascheduler.adapters.cloud.protocols import CloudCapacity

        impl = MagicMock()
        impl.get_capacity = AsyncMock(
            return_value={"test": CloudCapacity(name="test", current=2, max=5)}
        )
        mgr = CloudAPIManager(impl=impl, apis_compat={}, log=MagicMock())

        result = await mgr.get_capacity()

        assert isinstance(result, dict)
        assert "test" in result
        cap = result["test"]
        assert isinstance(cap, CloudCapacity)
        assert cap.name == "test"
        assert cap.max == 5
        assert cap.current == 2


class TestCloudAPIManagerApis:
    """apis property returns compat objects with .config.max_nodes."""

    def test_returns_compat_objects(self) -> None:
        config = MagicMock()
        config.max_nodes = 10
        apis = {"test": _CloudAPICompat(name="test", config=config)}
        mgr = CloudAPIManager(impl=MagicMock(), apis_compat=apis, log=MagicMock())

        assert "test" in mgr.apis
        assert mgr.apis["test"].name == "test"
        assert mgr.apis["test"].config.max_nodes == 10


class TestCloudAPIManagerStop:
    """stop() delegates to impl.stop()."""

    @pytest.mark.asyncio
    async def test_delegates_to_impl(self) -> None:
        impl = MagicMock()
        impl.stop = AsyncMock()
        mgr = CloudAPIManager(impl=impl, apis_compat={}, log=MagicMock())

        await mgr.stop()

        impl.stop.assert_awaited_once()
