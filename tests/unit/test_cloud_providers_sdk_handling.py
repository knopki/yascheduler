# FILE: tests/unit/test_cloud_providers_sdk_handling.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Tests for graceful handling of missing provider SDKs.
#   SCOPE: Provider module importability, _*_AVAILABLE flags, adapter factory error handling,
#          CloudProvisionerImpl behavior with unavailable SDKs.
#   DEPENDS: M-CLOUD-AZ, M-CLOUD-HETZNER, M-CLOUD-UPCLOUD, M-CLOUD-ADAPTERS, M-CLOUD-MANAGER
#   LINKS: M-CLOUD-AZ, M-CLOUD-HETZNER, M-CLOUD-UPCLOUD, M-CLOUD-ADAPTERS, M-CLOUD-MANAGER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestProviderModulesImportable - Provider modules importable with _*_AVAILABLE flags
#   TestAdapterFactoryHandlesMissingSDK - Adapter factories handle missing SDKs gracefully
#   TestResolveAdapterHandlesImportError - _resolve_adapter catches ImportError
#   TestCloudProvisionerImplHandlesMissingSDK - CloudProvisionerImpl handles create_node ImportError
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial SDK handling tests.
# END_CHANGE_SUMMARY

"""SDK handling tests: graceful missing provider SDKs."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.adapters.cloud.manager import CloudAllocateError


def _make_mock_adapter(
    name: str = "test",
    priority: int = 10,
    max_nodes: int = 5,
) -> tuple[MagicMock, MagicMock]:
    """Minimal mock adapter for provisioner tests."""
    adapter = MagicMock()
    adapter.name = name
    adapter.op_limit = 5
    adapter.create_node_conn_timeout = 30
    adapter.create_node_timeout = 300
    sem = asyncio.Semaphore(1)
    adapter.get_op_semaphore.return_value = sem

    def _check(platform: str) -> bool:
        return platform in ("linux",)

    adapter.supported_platform_checks = (_check,)

    config = MagicMock()
    config.prefix = name.split("-")[0]
    config.max_nodes = max_nodes
    config.priority = priority
    config.username = "root"
    config.jump_host = None
    config.jump_username = None

    return adapter, config


def _make_mock_node_repo(**kwargs: MagicMock) -> MagicMock:
    """Minimal mock NodeRepository."""
    repo = MagicMock()
    repo.list_all = AsyncMock(return_value=kwargs.get("nodes", []))
    repo.add_tmp = AsyncMock(return_value="tmp-ip")
    repo.add = AsyncMock()
    repo.remove = AsyncMock()
    repo.disable = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    return repo


# =============================================================================
# Tests
# =============================================================================


class TestProviderModulesImportable:
    """Provider modules are importable even when SDKs are missing."""

    def test_az_module_importable(self) -> None:
        """az module can be imported and has _AZURE_AVAILABLE flag."""
        import yascheduler.adapters.cloud.providers.az as az_mod

        assert hasattr(az_mod, "_AZURE_AVAILABLE")
        # Flag is True if SDK installed, False otherwise — either is acceptable

    def test_hetzner_module_importable(self) -> None:
        """hetzner module can be imported and has _HETZNER_AVAILABLE flag."""
        import yascheduler.adapters.cloud.providers.hetzner as hetzner_mod

        assert hasattr(hetzner_mod, "_HETZNER_AVAILABLE")

    def test_upcloud_module_importable(self) -> None:
        """upcloud module can be imported and has _UPCLOUD_AVAILABLE flag."""
        import yascheduler.adapters.cloud.providers.upcloud as upcloud_mod

        assert hasattr(upcloud_mod, "_UPCLOUD_AVAILABLE")


class TestAdapterFactoryHandlesMissingSDK:
    """Factory functions return adapters even when SDKs are not installed.

    The adapter factory functions (get_azure_adapter etc.) do NOT call any
    SDK functions — they just create a CloudAdapter wrapping the function
    references. SDK ImportErrors only occur when create_node/delete_node
    are actually invoked.
    """

    def test_get_azure_adapter_works_without_sdk(self) -> None:
        """get_azure_adapter returns CloudAdapter even without Azure SDK."""
        from yascheduler.adapters.cloud.adapters import get_azure_adapter

        adapter = get_azure_adapter("az-test")
        assert adapter.name == "az-test"

    def test_get_hetzner_adapter_works_without_sdk(self) -> None:
        """get_hetzner_adapter returns CloudAdapter even without Hetzner SDK."""
        from yascheduler.adapters.cloud.adapters import get_hetzner_adapter

        adapter = get_hetzner_adapter("hetzner-test")
        assert adapter.name == "hetzner-test"

    def test_get_upcloud_adapter_works_without_sdk(self) -> None:
        """get_upcloud_adapter returns CloudAdapter even without UpCloud SDK."""
        from yascheduler.adapters.cloud.adapters import get_upcloud_adapter

        adapter = get_upcloud_adapter("upcloud-test")
        assert adapter.name == "upcloud-test"


class TestResolveAdapterHandlesImportError:
    """_resolve_adapter in cloud_api_manager handles ImportError gracefully."""

    def test_resolve_adapter_catches_import_error(self) -> None:
        """_resolve_adapter returns None and logs error when getter raises ImportError."""
        from yascheduler.clouds.cloud_api_manager import _resolve_adapter

        cfg = MagicMock()
        cfg.prefix = "az"
        log = MagicMock()

        getter_that_raises = MagicMock(side_effect=ImportError("SDK not installed"))

        with patch.dict(
            "yascheduler.clouds.cloud_api_manager.CLOUD_ADAPTER_GETTERS",
            {"az": getter_that_raises},
        ):
            result = _resolve_adapter(cfg, log)

        assert result is None
        log.error.assert_called_once()


class TestCloudProvisionerImplHandlesMissingSDK:
    """CloudProvisionerImpl handles create_node ImportError from SDKs."""

    @pytest.mark.asyncio
    async def test_allocate_import_error_wrapped_as_cloud_allocate_error(
        self,
    ) -> None:
        """ImportError from create_node (missing SDK) becomes CloudAllocateError."""
        adapter, config = _make_mock_adapter(name="test")

        async def _fail_create(**kwargs: object) -> str:
            raise ImportError("Azure SDK not installed")

        adapter.create_node = _fail_create
        node_repo = _make_mock_node_repo()
        engines = MagicMock()
        engines.filter.return_value = engines
        engines.get_platform_packages.return_value = ["pkg"]
        local_config = MagicMock()

        from yascheduler.adapters.cloud.manager import CloudProvisionerImpl

        prov = CloudProvisionerImpl(
            adapters={"test": adapter},
            configs={"test": config},
            node_repo=node_repo,
            machine_gateway=MagicMock(),
            local_config=local_config,
            remote_config=MagicMock(),
            engines=engines,
            log=MagicMock(),
        )

        with (
            patch.object(
                CloudProvisionerImpl, "_get_ssh_key_sync", return_value=MagicMock()
            ),
            pytest.raises(CloudAllocateError, match="Create node error"),
        ):
            await prov.allocate(["linux"])

        node_repo.remove.assert_awaited_with("tmp-ip")
