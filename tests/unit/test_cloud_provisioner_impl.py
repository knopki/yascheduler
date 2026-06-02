# FILE: tests/unit/test_cloud_provisioner_impl.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for CloudProvisionerImpl — allocate, deallocate, capacity, provider selection.
#   SCOPE: CloudProvisionerImpl with all provider SDKs, NodeRepository, and SSHMachineGateway mocked.
#   DEPENDS: M-CLOUD-PROVISIONER, M-DOMAIN-PORTS, M-CLOUD-ADAPTERS-NEW
#   LINKS: M-CLOUD-PROVISIONER, M-CLOUD-ADAPTERS-NEW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestAllocate - allocate happy path, no provider, overloaded provider, cleanup on failure
#   TestAllocateWithTracking - dedup, error handling, throttle passthrough
#   TestDeallocate - happy path, node not found, unsupported cloud
#   TestCapacity - capacity aggregation
#   TestSelectBestProvider - priority sorting, max_nodes filtering, platform filtering
#   TestMarkTaskDone - on_tasks set management
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial tests for CloudProvisionerImpl.
# END_CHANGE_SUMMARY

# ruff: noqa: ANN401

from __future__ import annotations

import asyncio
import sys
from pathlib import Path, PurePath
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.adapters.cloud.cloud_config import CloudConfig
from yascheduler.adapters.cloud.manager import (
    CloudAllocateError,
    CloudProvisionerImpl,
    CloudSetupError,
)
from yascheduler.adapters.cloud.protocols import CloudCapacity
from yascheduler.adapters.cloud.ssh_keys import get_or_create_ssh_key
from yascheduler.domain.model import Node

# =============================================================================
# Helpers
# =============================================================================

_SENTINEL = object()


def _make_mock_adapter(
    name: str = "test-cloud",
    priority: int = 10,
    max_nodes: int = 5,
    platform_support: bool = True,
) -> tuple[MagicMock, MagicMock]:
    """Create a mock CloudAdapter and its config."""
    adapter = MagicMock()
    adapter.name = name
    adapter.op_limit = 5
    adapter.create_node_conn_timeout = 30
    adapter.create_node_timeout = 300

    # Semaphore mock — stateful mock avoids asyncio.Semaphore which needs event loop on 3.9
    sem = MagicMock()
    _locked = False

    def _acquire() -> None:
        nonlocal _locked
        _locked = True

    def _release() -> None:
        nonlocal _locked
        _locked = False

    sem.locked.side_effect = lambda: _locked
    sem.acquire = AsyncMock(side_effect=_acquire)
    sem.release = MagicMock(side_effect=_release)
    adapter.get_op_semaphore.return_value = sem

    # Platform check
    def _check(platform: str) -> bool:
        return (
            platform in ("linux", "debian-11", "debian-10", "windows")
            if platform_support
            else platform == "unsupported"
        )

    adapter.supported_platform_checks = (_check,)

    # Create/delete callables
    async def _create_node(
        log: Any = None,
        cfg: Any = None,
        key: Any = None,
        cloud_config: Any = None,
    ) -> str:
        return "10.0.0.1"

    adapter.create_node = _create_node

    async def _delete_node(log: Any = None, cfg: Any = None, host: Any = None) -> None:
        pass

    adapter.delete_node = _delete_node

    config = MagicMock()
    config.prefix = name.split("-")[0]
    config.max_nodes = max_nodes
    config.priority = priority
    config.username = "root"
    config.jump_host = None
    config.jump_username = None

    return adapter, config


def _make_mock_gateway(**kwargs: Any) -> MagicMock:
    """Create a mock SSHMachineGateway."""
    gw = MagicMock()

    async def _connect(**kw: Any) -> MagicMock:
        machine = MagicMock()
        machine.ip = kw.get("ip", "10.0.0.1")
        return machine

    gw.connect = _connect

    async def _run(machine: Any, cmd: str) -> MagicMock:
        result = MagicMock()
        result.exit_code = 0
        result.stdout = ""
        result.stderr = ""
        return result

    gw.run = _run

    async def _setup_node(ip: str, engines: Any) -> None:
        pass

    gw.setup_node = _setup_node

    async def _get_cpu_cores(ip: str) -> int:
        return kwargs.get("ncpus", 4)

    gw.get_cpu_cores = _get_cpu_cores

    return gw


def _make_mock_node_repo(**kwargs: Any) -> MagicMock:
    """Create a mock NodeRepository with AsyncMocks for async methods."""
    repo = MagicMock()
    nodes = kwargs.get("nodes", [])
    get_result = kwargs.get("get_result", _SENTINEL)

    repo.list_all = AsyncMock(return_value=nodes)
    repo.add_tmp = AsyncMock(return_value="tmp-ip")
    repo.add = AsyncMock()
    repo.remove = AsyncMock()
    repo.disable = AsyncMock()
    repo.get = AsyncMock(return_value=None if get_result is _SENTINEL else get_result)
    return repo


@pytest.fixture
def mock_engines() -> MagicMock:
    """Create mock EngineRepository with filter chain."""
    eng = MagicMock()
    eng.filter.return_value = eng
    eng.get_platform_packages.return_value = ["vim", "htop"]
    return eng


@pytest.fixture
def mock_local_config() -> MagicMock:
    """Create mock ConfigLocal with fake keys_dir."""
    cfg = MagicMock()
    mock_keys_dir = MagicMock(spec=Path)
    mock_keys_dir.iterdir.return_value = []
    cfg.keys_dir = mock_keys_dir
    cfg.get_private_keys.return_value = []
    return cfg


@pytest.fixture
def mock_remote_config() -> MagicMock:
    """Create mock ConfigRemote."""
    cfg = MagicMock()
    cfg.data_dir = PurePath("./data")
    cfg.engines_dir = PurePath("./data/engines")
    cfg.tasks_dir = PurePath("./data/tasks")
    return cfg


@pytest.fixture
def mock_logger() -> MagicMock:
    """Create mock logger."""
    return MagicMock()


# =============================================================================
# Factory helper
# =============================================================================


def make_provisioner(
    adapters: dict[str, MagicMock] | None = None,
    configs: dict[str, MagicMock] | None = None,
    node_repo: MagicMock | None = None,
    gateway: MagicMock | None = None,
    local_config: MagicMock | None = None,
    remote_config: MagicMock | None = None,
    engines: MagicMock | None = None,
    logger: MagicMock | None = None,
) -> CloudProvisionerImpl:
    """Helper to construct a CloudProvisionerImpl with defaults."""
    # Python 3.9: asyncio.Lock() requires a running event loop during init.
    if sys.version_info < (3, 10):
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
    return CloudProvisionerImpl(
        adapters=adapters or {},  # type: ignore[arg-type]
        configs=configs or {},  # type: ignore[arg-type]
        node_repo=node_repo or _make_mock_node_repo(),
        machine_gateway=gateway or _make_mock_gateway(),
        local_config=local_config or MagicMock(),
        remote_config=remote_config or MagicMock(),
        engines=engines or MagicMock(),
        log=logger or MagicMock(),
    )


# =============================================================================
# Tests
# =============================================================================


class TestBool:
    """__bool__ reflects adapter presence."""

    def test_true_when_adapters_present(self) -> None:
        a, c = _make_mock_adapter()
        prov = make_provisioner(adapters={"test": a}, configs={"test": c})
        assert bool(prov) is True

    def test_false_when_no_adapters(self) -> None:
        prov = make_provisioner()
        assert bool(prov) is False


class TestApis:
    """apis property returns adapters dict."""

    def test_apis_returns_adapters(self) -> None:
        a, c = _make_mock_adapter()
        prov = make_provisioner(adapters={"test": a}, configs={"test": c})
        assert prov.apis == {"test": a}


class TestAllocate:
    """allocate() happy path and error cases."""

    @pytest.mark.asyncio
    async def test_allocate_happy_path(
        self, mock_engines: MagicMock, mock_local_config: MagicMock
    ) -> None:
        """Full flow: select provider -> create VM -> SSH -> cloud-init -> setup -> add node."""
        adapter, config = _make_mock_adapter(name="test", priority=10)
        gw = _make_mock_gateway(ncpus=4)
        node_repo = _make_mock_node_repo()

        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            node_repo=node_repo,
            gateway=gw,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        with patch(
            "yascheduler.adapters.cloud.manager.CloudProvisionerImpl._get_ssh_key",
            new=AsyncMock(return_value=MagicMock()),
        ):
            node = await prov.allocate(["linux"])

        assert isinstance(node, Node)
        assert node.ip == "10.0.0.1"
        assert node.ncpus == 4
        assert node.cloud == "test"
        assert node.enabled is True
        assert node.port == 22
        node_repo.add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allocate_no_provider(self) -> None:
        """Raises CloudAllocateError when no provider supports the platform."""
        adapter, config = _make_mock_adapter(platform_support=False)
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
        )

        with pytest.raises(CloudAllocateError, match="No available provider"):
            await prov.allocate(["windows"])

    @pytest.mark.asyncio
    async def test_allocate_overloaded_provider(self) -> None:
        """Raises CloudAllocateError when provider semaphore is locked."""
        adapter, config = _make_mock_adapter(name="test")
        # Lock the semaphore
        sem = adapter.get_op_semaphore()
        await sem.acquire()

        node_repo = _make_mock_node_repo()
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            node_repo=node_repo,
        )

        with pytest.raises(CloudAllocateError, match="overloaded"):
            await prov.allocate(["linux"])

    @pytest.mark.asyncio
    async def test_allocate_create_node_failure(
        self, mock_local_config: MagicMock, mock_engines: MagicMock
    ) -> None:
        """Cleans up tmp node when VM creation fails."""
        adapter, config = _make_mock_adapter(name="test")

        async def _fail(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("SDK failure")

        adapter.create_node = _fail

        node_repo = _make_mock_node_repo()
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            node_repo=node_repo,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        with pytest.raises(CloudAllocateError, match="Create node error"):
            await prov.allocate(["linux"])

    @pytest.mark.asyncio
    async def test_allocate_setup_failure_cleans_up_vm(
        self, mock_local_config: MagicMock, mock_engines: MagicMock
    ) -> None:
        """Deletes VM when SSH/cloud-init/setup fails."""
        adapter, config = _make_mock_adapter(name="test")
        gw = MagicMock()

        async def _connect_fail(**kw: Any) -> Any:
            raise RuntimeError("SSH timeout")

        gw.connect = _connect_fail

        node_repo = _make_mock_node_repo()
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            node_repo=node_repo,
            gateway=gw,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        adapter.delete_node = AsyncMock()

        with (
            patch(
                "yascheduler.adapters.cloud.manager.CloudProvisionerImpl._get_ssh_key",
                new=AsyncMock(return_value=MagicMock()),
            ),
            pytest.raises(CloudSetupError, match="SSH connect to"),
        ):
            await prov.allocate(["linux"])

        adapter.delete_node.assert_awaited_once()


class TestAllocateWithTracking:
    """Backward-compat allocate_with_tracking()."""

    @pytest.mark.asyncio
    async def test_tracking_dedup(self) -> None:
        """Same on_task ignored if already in flight."""
        adapter, config = _make_mock_adapter(name="test")
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
        )
        prov.on_tasks.add(42)

        result = await prov.allocate_with_tracking(on_task=42, platforms=["linux"])
        assert result is None

    @pytest.mark.asyncio
    async def test_tracking_error_returns_none(self) -> None:
        """Error during allocate returns None and clears tracking."""
        adapter, config = _make_mock_adapter(name="test", platform_support=False)
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
        )

        result = await prov.allocate_with_tracking(on_task=99, platforms=["windows"])
        assert result is None
        assert 99 not in prov.on_tasks

    @pytest.mark.asyncio
    async def test_tracking_success_returns_ip(
        self, mock_local_config: MagicMock, mock_engines: MagicMock
    ) -> None:
        """Successful allocate_with_tracking returns IP string."""
        adapter, config = _make_mock_adapter(name="test", priority=10)
        gw = _make_mock_gateway(ncpus=4)
        node_repo = _make_mock_node_repo()
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            gateway=gw,
            node_repo=node_repo,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        with patch(
            "yascheduler.adapters.cloud.manager.CloudProvisionerImpl._get_ssh_key",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await prov.allocate_with_tracking(on_task=7, platforms=["linux"])

        assert result == "10.0.0.1"
        assert 7 in prov.on_tasks  # caller must call mark_task_done


class TestDeallocate:
    """deallocate() variations."""

    @pytest.mark.asyncio
    async def test_deallocate_happy_path(self) -> None:
        """Disable, delete VM, remove from DB."""
        adapter, config = _make_mock_adapter(name="test-cloud")
        node = Node(ip="10.0.0.1", ncpus=4, cloud="test-cloud")
        node_repo = _make_mock_node_repo(get_result=node)
        adapter.delete_node = AsyncMock()

        prov = make_provisioner(
            adapters={"test-cloud": adapter},
            configs={"test-cloud": config},
            node_repo=node_repo,
        )

        await prov.deallocate("10.0.0.1")

        node_repo.disable.assert_awaited_once_with("10.0.0.1")
        adapter.delete_node.assert_awaited_once()
        node_repo.remove.assert_awaited_once_with("10.0.0.1")

    @pytest.mark.asyncio
    async def test_deallocate_node_not_found(self) -> None:
        """Silent no-op when node doesn't exist."""
        node_repo = _make_mock_node_repo()
        node_repo.get = AsyncMock(return_value=None)

        prov = make_provisioner(node_repo=node_repo)
        await prov.deallocate("10.0.0.99")  # should not raise

    @pytest.mark.asyncio
    async def test_deallocate_no_cloud(self) -> None:
        """Silent no-op when node has no cloud attribute."""
        node = Node(ip="10.0.0.1", ncpus=4, cloud=None)
        node_repo = _make_mock_node_repo(get_result=node)

        prov = make_provisioner(node_repo=node_repo)
        await prov.deallocate("10.0.0.1")

    @pytest.mark.asyncio
    async def test_deallocate_unsupported_cloud(self) -> None:
        """Logs warning when cloud provider is not configured."""
        node = Node(ip="10.0.0.1", ncpus=4, cloud="unknown-cloud")
        node_repo = _make_mock_node_repo(get_result=node)
        log = MagicMock()

        prov = make_provisioner(node_repo=node_repo, logger=log)
        await prov.deallocate("10.0.0.1")

        log.warning.assert_called()


class TestCapacity:
    """capacity() and get_capacity()."""

    @pytest.mark.asyncio
    async def test_capacity_empty(self) -> None:
        """No nodes and no adapters -> empty dict."""
        prov = make_provisioner()
        result = await prov.capacity()
        assert result == {}

    @pytest.mark.asyncio
    async def test_capacity_with_nodes(self) -> None:
        """Available = max_nodes - current_count."""
        adapter, config = _make_mock_adapter(name="test-cloud", max_nodes=5)
        nodes = [
            Node(ip="10.0.0.1", ncpus=4, cloud="test-cloud"),
            Node(ip="10.0.0.2", ncpus=4, cloud="test-cloud"),
        ]
        node_repo = _make_mock_node_repo(nodes=nodes)

        prov = make_provisioner(
            adapters={"test-cloud": adapter},
            configs={"test-cloud": config},
            node_repo=node_repo,
        )

        result = await prov.capacity()
        assert result == {"test-cloud": 3}  # 5 - 2

    @pytest.mark.asyncio
    async def test_capacity_full(self) -> None:
        """Zero available when at max_nodes."""
        adapter, config = _make_mock_adapter(name="test-cloud", max_nodes=2)
        nodes = [
            Node(ip="10.0.0.1", ncpus=4, cloud="test-cloud"),
            Node(ip="10.0.0.2", ncpus=4, cloud="test-cloud"),
        ]
        node_repo = _make_mock_node_repo(nodes=nodes)

        prov = make_provisioner(
            adapters={"test-cloud": adapter},
            configs={"test-cloud": config},
            node_repo=node_repo,
        )

        result = await prov.capacity()
        assert result == {"test-cloud": 0}

    @pytest.mark.asyncio
    async def test_get_capacity_returns_cloud_capacity_objects(self) -> None:
        """get_capacity returns CloudCapacity objects."""
        adapter, config = _make_mock_adapter(name="test-cloud", max_nodes=5)
        node_repo = _make_mock_node_repo()

        prov = make_provisioner(
            adapters={"test-cloud": adapter},
            configs={"test-cloud": config},
            node_repo=node_repo,
        )

        result = await prov.get_capacity()
        assert isinstance(result, dict)
        assert "test-cloud" in result
        cap = result["test-cloud"]
        assert isinstance(cap, CloudCapacity)
        assert cap.name == "test-cloud"
        assert cap.max == 5
        assert cap.current == 0


class TestSelectBestProvider:
    """_select_best_provider() logic."""

    @pytest.mark.asyncio
    async def test_select_by_priority(self) -> None:
        """Higher priority provider is chosen."""
        a1, c1 = _make_mock_adapter(name="low", priority=1)
        a2, c2 = _make_mock_adapter(name="high", priority=10)

        prov = make_provisioner(
            adapters={"low": a1, "high": a2},
            configs={"low": c1, "high": c2},
        )

        chosen = await prov._select_best_provider(["linux"])
        assert chosen is not None
        assert chosen.name == "high"

    @pytest.mark.asyncio
    async def test_select_filters_by_max_nodes(self) -> None:
        """Provider at max_nodes capacity is excluded."""
        a1, c1 = _make_mock_adapter(name="full", max_nodes=1)
        a2, c2 = _make_mock_adapter(name="free", max_nodes=5)

        nodes = [Node(ip="10.0.0.1", ncpus=4, cloud="full")]
        node_repo = _make_mock_node_repo(nodes=nodes)

        prov = make_provisioner(
            adapters={"full": a1, "free": a2},
            configs={"full": c1, "free": c2},
            node_repo=node_repo,
        )

        chosen = await prov._select_best_provider(["linux"])
        assert chosen is not None
        assert chosen.name == "free"

    @pytest.mark.asyncio
    async def test_select_filters_by_platform(self) -> None:
        """Provider that doesn't support any requested platform is excluded."""
        a1, c1 = _make_mock_adapter(name="linux-only", priority=10)
        a2, c2 = _make_mock_adapter(name="win-only", priority=5, platform_support=False)

        prov = make_provisioner(
            adapters={"linux-only": a1, "win-only": a2},
            configs={"linux-only": c1, "win-only": c2},
        )

        chosen = await prov._select_best_provider(["linux"])
        assert chosen is not None
        assert chosen.name == "linux-only"

    @pytest.mark.asyncio
    async def test_select_returns_none_when_all_excluded(self) -> None:
        """Returns None when no provider can satisfy request."""
        a1, c1 = _make_mock_adapter(platform_support=False)

        prov = make_provisioner(
            adapters={"only": a1},
            configs={"only": c1},
        )

        chosen = await prov._select_best_provider(["windows"])
        assert chosen is None


class TestMarkTaskDone:
    """mark_task_done management."""

    def test_removes_existing(self) -> None:
        prov = make_provisioner()
        prov.on_tasks.add(42)
        prov.mark_task_done(42)
        assert 42 not in prov.on_tasks

    def test_no_error_on_missing(self) -> None:
        prov = make_provisioner()
        prov.mark_task_done(99)  # should not raise


class TestStop:
    """stop() is a no-op."""

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        prov = make_provisioner()
        await prov.stop()


class TestIsPlatformSupported:
    """_is_platform_supported() edge cases."""

    def test_supported(self) -> None:
        adapter, _ = _make_mock_adapter()
        prov = make_provisioner()
        assert prov._is_platform_supported(adapter, "linux") is True

    def test_not_supported(self) -> None:
        adapter, _ = _make_mock_adapter(platform_support=False)
        prov = make_provisioner()
        assert prov._is_platform_supported(adapter, "windows") is False


class TestSshKeyGeneration:
    """get_or_create_ssh_key() — SSH key load/generate (filesystem)."""

    def test_generates_new_key_when_none_exists(
        self, mock_local_config: MagicMock
    ) -> None:
        """Generates new SSH key and writes to keys_dir when no existing key."""
        mock_log = MagicMock()

        mock_key = MagicMock()
        mock_key.get_fingerprint.return_value = "md5:abcd"

        with (
            patch(
                "yascheduler.adapters.cloud.ssh_keys.generate_private_key",
                return_value=mock_key,
            ) as mock_gen,
            patch(
                "yascheduler.adapters.cloud.ssh_keys.get_rnd_name",
                return_value="yakey-rnd123",
            ),
        ):
            result = get_or_create_ssh_key(mock_local_config.keys_dir, mock_log)

        mock_gen.assert_called_once_with(alg_name="ssh-rsa", comment="yakey-rnd123")
        mock_local_config.keys_dir.__truediv__.assert_called_once_with("yakey-rnd123")
        result_path = mock_local_config.keys_dir.__truediv__.return_value
        mock_key.write_private_key.assert_called_once_with(result_path)
        result_path.chmod.assert_called_once_with(0o600)
        assert result is mock_key

    def test_loads_existing_key(self) -> None:
        """Loads existing SSH key from keys_dir."""
        keys_dir = MagicMock(spec=Path)
        existing_file = MagicMock(spec=Path)
        existing_file.name = "yakey-existing"
        existing_file.is_file.return_value = True
        keys_dir.iterdir.return_value = [existing_file]
        mock_log = MagicMock()

        mock_key = MagicMock()
        mock_key.get_fingerprint.return_value = "md5:efgh"

        with patch(
            "yascheduler.adapters.cloud.ssh_keys.read_private_key",
            return_value=mock_key,
        ) as mock_read:
            result = get_or_create_ssh_key(keys_dir, mock_log)

        mock_read.assert_called_once_with(existing_file)
        mock_key.set_comment.assert_called_once_with("yakey-existing")
        assert result is mock_key


class TestCloudConfigGeneration:
    """_get_cloud_config_data() — cloud-config building with engine packages."""

    @pytest.mark.asyncio
    async def test_cloud_config_with_engine_packages(
        self, mock_engines: MagicMock
    ) -> None:
        """Returns CloudConfig with packages from matched engines."""
        adapter, config = _make_mock_adapter(name="test")
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            engines=mock_engines,
        )

        cc = await prov._get_cloud_config_data(adapter)

        assert isinstance(cc, CloudConfig)
        assert cc.package_upgrade is True
        assert "vim" in cc.packages
        assert "htop" in cc.packages
        mock_engines.filter.assert_called_once()
