# FILE: tests/unit/test_cloud_provisioner_impl.py
# VERSION: 2.12.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for CloudProvisionerImpl — allocate, deallocate, select_provider.
#   SCOPE: CloudProvisionerImpl with all provider SDKs and SSHMachineGateway mocked (no DB).
#   DEPENDS: M-CLOUD-PROVISIONER, M-DOMAIN-PORTS, M-CLOUD-ADAPTERS-NEW
#   LINKS: M-CLOUD-PROVISIONER, M-CLOUD-ADAPTERS-NEW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestBool - __bool__ reflects adapter presence
#   TestAllocate - allocate happy path, no provider, create_node failure, setup failure
#   TestDeallocate - happy path, unsupported cloud, no config, no-cloud no-op
#   TestStop - stop drains machine_gateway via disconnect_all (happy path + idempotency)
#   TestIsPlatformSupported - _is_platform_supported edge cases
#   TestSshKeyGeneration - get_or_create_ssh_key file ops
#   TestCloudConfigGeneration - cloud-config building with engine packages
#   TestSelectProvider - select_provider sync port: capacity, platform, throttle
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.12.0 - cloud-port-node-arg: allocate/deallocate call sites pass a tmp Node (was NodeId/cloud+ip); added _tmp_node helper + test_deallocate_no_cloud_logs_and_returns.
#   PREVIOUS_CHANGE: v2.11.0 - simplify-cloud-connect-node-args: _make_mock_repository records connect calls; happy-path test asserts connect(node=..., no username/port kwargs, same-identity return); setup-failure test asserts disconnect before delete_node.
# END_CHANGE_SUMMARY

# ruff: noqa: ANN401

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path, PurePath
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.domain.model import Node, NodeId
from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
from yascheduler.infra.cloud.cloud_init import CloudInitConfig
from yascheduler.infra.cloud.manager import (
    CloudAllocateError,
    CloudProvisionerImpl,
    CloudSetupError,
)
from yascheduler.infra.cloud.ssh_keys import get_or_create_ssh_key

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


def _make_mock_repository(**kwargs: Any) -> MagicMock:
    """Create a mock SSHMachineRepository.

    Records every connect call's kwargs in ``repo.connect_calls`` so tests can
    assert the node is passed straight through and no ``username``/``port``
    kwargs are supplied (they now come from ``node.username``/``node.port``).
    """
    repo = MagicMock()
    repo.connect_calls = []

    async def _connect(**kw: Any) -> MagicMock:
        repo.connect_calls.append(kw)
        machine = MagicMock()
        node = kw.get("node")
        machine.ip = node.ip if node is not None else "10.0.0.1"
        return machine

    repo.connect = _connect

    return repo


def _make_mock_operations(**kwargs: Any) -> MagicMock:
    """Create a mock SSHMachineOperations."""
    ops = MagicMock()

    async def _run(machine: Any, cmd: str) -> MagicMock:
        result = MagicMock()
        result.exit_code = 0
        result.stdout = ""
        result.stderr = ""
        return result

    ops.run = _run

    async def _setup_node(ip: str, engines: Any) -> None:
        pass

    ops.setup_node = _setup_node

    async def _get_cpu_cores(ip: str) -> int:
        return kwargs.get("ncpus", 4)

    ops.get_cpu_cores = _get_cpu_cores

    return ops


def _tmp_node(node_id: int = 999, cloud: str | None = "test") -> Node:
    """Build a tmp-node Node as the caller (allocate_task) would insert it.

    ``allocate`` receives this Node and overlays ip/cloud/username via
    ``replace`` after ``create_node`` returns the VM ip. The tmp node carries
    the default port=22 and the caller's cloud (== provider name).
    """
    return Node(
        node_id=NodeId(node_id),
        ip="",
        ncpus=0,
        enabled=False,
        cloud=cloud,
        username="root",
        port=22,
    )


@pytest.fixture
def mock_engines() -> MagicMock:
    """Create mock EngineRepository with filter chain."""
    eng = MagicMock()
    eng.filter.return_value = eng
    eng.get_platform_packages.return_value = ["vim", "htop"]
    return eng


@pytest.fixture
def mock_local_config() -> MagicMock:
    """Create mock LocalSettings with fake keys_dir.

    list_private_keys(cfg.keys_dir) calls keys_dir.iterdir() and filters
    is_file(); mock_keys_dir.iterdir returns [] so the result is an empty list.
    """
    cfg = MagicMock()
    mock_keys_dir = MagicMock(spec=Path)
    mock_keys_dir.iterdir.return_value = []
    cfg.keys_dir = mock_keys_dir
    return cfg


@pytest.fixture
def mock_remote_config() -> MagicMock:
    """Create mock RemoteDefaults."""
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
    adapters: dict[str, Any] | None = None,
    configs: dict[str, Any] | None = None,
    machine_repository: MagicMock | None = None,
    machine_operations: MagicMock | None = None,
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
        adapters=adapters or {},
        configs=configs or {},
        machine_repository=machine_repository or _make_mock_repository(),
        machine_operations=machine_operations or _make_mock_operations(),
        local_config=local_config or MagicMock(),
        remote_config=remote_config or MagicMock(),
        engines=engines or MagicMock(),
        log=logger or MagicMock(),
    )


# =============================================================================
# Tests
# =============================================================================


class TestAllocate:
    """allocate() happy path and error cases."""

    @pytest.mark.asyncio
    async def test_allocate_happy_path(
        self, mock_engines: MagicMock, mock_local_config: MagicMock
    ) -> None:
        """Full flow: create VM -> SSH -> cloud-init -> setup -> return Node."""
        adapter, config = _make_mock_adapter(name="test", priority=10)
        repo = _make_mock_repository()
        ops = _make_mock_operations(ncpus=4)

        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            machine_repository=repo,
            machine_operations=ops,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        with patch(
            "yascheduler.infra.cloud.manager.CloudProvisionerImpl._get_ssh_key",
            new=AsyncMock(return_value=MagicMock()),
        ):
            node = await prov.allocate("test", _tmp_node(999))

        assert isinstance(node, Node)
        assert node.node_id == NodeId(999)
        assert node.ip == "10.0.0.1"
        assert node.ncpus == 4
        assert node.cloud == "test"
        assert node.enabled is True
        assert node.port == 22
        # allocate constructs one Node (after create_node) and threads it to
        # connect; connect is called with node=... and NO username/port kwargs
        # (they come from node.username/node.port). The returned node is the
        # same identity (replace(node, enabled=True, ncpus)) — node_id == tmp_node_id.
        assert len(repo.connect_calls) == 1
        connect_kw = repo.connect_calls[0]
        assert "node" in connect_kw
        assert "username" not in connect_kw
        assert "port" not in connect_kw
        assert connect_kw["node"].node_id == NodeId(999)
        assert node.username == connect_kw["node"].username
        assert node.port == connect_kw["node"].port
        assert node.cloud == connect_kw["node"].cloud

    @pytest.mark.asyncio
    async def test_allocate_no_provider(self) -> None:
        """Raises CloudAllocateError when provider name is unknown."""
        prov = make_provisioner()

        with pytest.raises(CloudAllocateError, match="Unknown provider"):
            await prov.allocate("nonexistent", _tmp_node(1))

    @pytest.mark.asyncio
    async def test_allocate_create_node_failure(
        self, mock_local_config: MagicMock, mock_engines: MagicMock
    ) -> None:
        """Raises CloudAllocateError when VM creation fails."""
        adapter, config = _make_mock_adapter(name="test")

        async def _fail(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("SDK failure")

        adapter.create_node = _fail

        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            engines=mock_engines,
            local_config=mock_local_config,
        )

        with pytest.raises(CloudAllocateError, match="Create node error"):
            await prov.allocate("test", _tmp_node(1))

    @pytest.mark.asyncio
    async def test_allocate_setup_failure_cleans_up_vm(
        self, mock_local_config: MagicMock, mock_engines: MagicMock
    ) -> None:
        """Deletes VM when SSH/cloud-init/setup fails."""
        adapter, config = _make_mock_adapter(name="test")
        repo = MagicMock()

        async def _connect_fail(**kw: Any) -> Any:
            raise RuntimeError("SSH timeout")

        repo.connect = _connect_fail
        # Fix B: allocate now awaits machine_repository.disconnect on setup failure.
        repo.disconnect = AsyncMock()

        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            machine_repository=repo,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        adapter.delete_node = AsyncMock()
        disconnect_mock = AsyncMock()
        delete_mock = adapter.delete_node
        call_order: list[str] = []

        async def _record_disconnect(*args: Any, **kwargs: Any) -> None:
            call_order.append("disconnect")
            await disconnect_mock(*args, **kwargs)

        repo.disconnect = _record_disconnect

        async def _record_delete(*args: Any, **kwargs: Any) -> None:
            call_order.append("delete_node")
            await delete_mock(*args, **kwargs)

        adapter.delete_node = _record_delete

        with (
            patch(
                "yascheduler.infra.cloud.manager.CloudProvisionerImpl._get_ssh_key",
                new=AsyncMock(return_value=MagicMock()),
            ),
            pytest.raises(CloudSetupError, match="SSH connect to"),
        ):
            await prov.allocate("test", _tmp_node(1))

        # Setup-failure path: disconnect(node.node_id) is awaited BEFORE
        # delete_node, and node.node_id == tmp_node_id (the single identity
        # object allocate constructed after create_node).
        assert call_order == ["disconnect", "delete_node"]
        disconnect_mock.assert_awaited_once_with(NodeId(1))
        delete_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allocate_cloud_init_timeout_cleans_up_vm(
        self, mock_local_config: MagicMock, mock_engines: MagicMock
    ) -> None:
        """cloud-init status --wait exceeding adapter.create_node_timeout raises CloudSetupError and deletes the VM (no infinite worker pin)."""
        adapter, config = _make_mock_adapter(name="test")
        # Shrink timeout so the test stays fast.
        adapter.create_node_timeout = 0.05

        repo = MagicMock()
        ops = MagicMock()

        async def _connect(**kw: Any) -> Any:
            machine = MagicMock()
            machine.ip = kw.get("ip", "10.0.0.1")
            return machine

        repo.connect = _connect
        # Fix B: allocate now awaits machine_repository.disconnect on setup failure.
        repo.disconnect = AsyncMock()

        async def _hang(*args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(60)
            return MagicMock(exit_code=0, stdout="", stderr="")

        ops.run = _hang

        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            machine_repository=repo,
            machine_operations=ops,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        adapter.delete_node = AsyncMock()

        with (
            patch(
                "yascheduler.infra.cloud.manager.CloudProvisionerImpl._get_ssh_key",
                new=AsyncMock(return_value=MagicMock()),
            ),
            pytest.raises(CloudSetupError, match="timed out"),
        ):
            await prov.allocate("test", _tmp_node(1))

        adapter.delete_node.assert_awaited_once()


class TestDeallocate:
    """deallocate() variations."""

    @pytest.mark.asyncio
    async def test_deallocate_happy_path(self) -> None:
        """Calls adapter.delete_node with host=ip."""
        adapter, config = _make_mock_adapter(name="test-cloud")
        adapter.delete_node = AsyncMock()

        prov = make_provisioner(
            adapters={"test-cloud": adapter},
            configs={"test-cloud": config},
        )

        node = Node(
            node_id=NodeId(1),
            ip="10.0.0.1",
            ncpus=2,
            cloud="test-cloud",
            username="root",
            port=22,
            enabled=True,
        )
        await prov.deallocate(node)

        adapter.delete_node.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deallocate_unsupported_cloud(self) -> None:
        """Logs warning when cloud provider is not configured."""
        adapter, config = _make_mock_adapter(name="test-cloud")
        adapter.delete_node = AsyncMock()
        log = MagicMock()

        prov = make_provisioner(
            adapters={"test-cloud": adapter},
            configs={"test-cloud": config},
            logger=log,
        )

        node = Node(
            node_id=NodeId(1),
            ip="10.0.0.1",
            ncpus=2,
            cloud="unknown-cloud",
            username="root",
            port=22,
            enabled=True,
        )
        await prov.deallocate(node)

        adapter.delete_node.assert_not_awaited()
        log.warning.assert_called()

    @pytest.mark.asyncio
    async def test_deallocate_no_config(self) -> None:
        """Logs warning when cloud is in adapters but not in configs."""
        adapter, config = _make_mock_adapter(name="test-cloud")
        adapter.delete_node = AsyncMock()
        log = MagicMock()

        prov = make_provisioner(
            adapters={"test-cloud": adapter},
            configs={},
            logger=log,
        )

        node = Node(
            node_id=NodeId(1),
            ip="10.0.0.1",
            ncpus=2,
            cloud="test-cloud",
            username="root",
            port=22,
            enabled=True,
        )
        await prov.deallocate(node)

        adapter.delete_node.assert_not_awaited()
        log.warning.assert_called()

    @pytest.mark.asyncio
    async def test_deallocate_no_cloud_logs_and_returns(self) -> None:
        """node.cloud is None -> no provider SDK invoked; adapter logs and returns."""
        adapter, config = _make_mock_adapter(name="test-cloud")
        adapter.delete_node = AsyncMock()
        log = MagicMock()

        prov = make_provisioner(
            adapters={"test-cloud": adapter},
            configs={"test-cloud": config},
            logger=log,
        )

        node = Node(
            node_id=NodeId(1),
            ip="10.0.0.1",
            ncpus=2,
            cloud=None,
            username="root",
            port=22,
            enabled=True,
        )
        await prov.deallocate(node)

        adapter.delete_node.assert_not_awaited()
        log.warning.assert_called()


class TestStop:
    """stop() drains machine_repository via disconnect_all."""

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        """stop() awaits machine_repository.disconnect_all exactly once."""
        repo = MagicMock()
        repo.disconnect_all = AsyncMock()

        prov = make_provisioner(machine_repository=repo)

        await prov.stop()

        repo.disconnect_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_idempotent_under_repeated_calls(self) -> None:
        """Calling stop() twice does not raise; disconnect_all is awaited on the second call too (spec: idempotency guard)."""
        repo = MagicMock()
        repo.disconnect_all = AsyncMock()

        prov = make_provisioner(machine_repository=repo)

        await prov.stop()
        await prov.stop()

        assert repo.disconnect_all.await_count == 2


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
                "yascheduler.infra.cloud.ssh_keys.generate_private_key",
                return_value=mock_key,
            ) as mock_gen,
            patch(
                "yascheduler.infra.cloud.ssh_keys.get_rnd_name",
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
            "yascheduler.infra.cloud.ssh_keys.read_private_key",
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
        """Returns CloudInitConfig with packages from matched engines."""
        adapter, _config = _make_mock_adapter(name="test")
        cloud_config = ConfigCloudHetzner(package_upgrade=True)
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": cloud_config},
            engines=mock_engines,
        )

        cc = await prov._get_cloud_config_data(adapter, cloud_config)

        assert isinstance(cc, CloudInitConfig)
        assert cc.package_upgrade is True
        assert "vim" in cc.packages
        assert "htop" in cc.packages
        mock_engines.filter.assert_called_once()

    @pytest.mark.asyncio
    async def test_cloud_config_package_upgrade_sourced_from_per_cloud_config(
        self, mock_engines: MagicMock
    ) -> None:
        """package_upgrade is sourced from config.package_upgrade (False propagates)."""
        adapter, _config = _make_mock_adapter(name="test")
        cloud_config = ConfigCloudHetzner(package_upgrade=False)
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": cloud_config},
            engines=mock_engines,
        )

        cc = await prov._get_cloud_config_data(adapter, cloud_config)

        assert isinstance(cc, CloudInitConfig)
        assert cc.package_upgrade is False

    @pytest.mark.asyncio
    async def test_cloud_config_render_serializes(self) -> None:
        """CloudInitConfig.render() produces stable #cloud-config JSON (asdict canary)."""
        cc = CloudInitConfig(
            bootcmd=("echo hi", ["mkdir", "/x"]),
            package_upgrade=True,
            packages=["vim", "htop"],
        )
        rendered = cc.render()
        assert rendered.startswith("#cloud-config\n")
        payload = json.loads(rendered[len("#cloud-config\n") :])
        assert payload["bootcmd"] == ["echo hi", ["mkdir", "/x"]]
        assert payload["packages"] == ["vim", "htop"]
        assert payload["package_upgrade"] is True

    def test_render_omits_empty_bootcmd_and_packages(self) -> None:
        """Empty bootcmd/packages omitted — cloud-init schema rejects [] (minItems: 1, exit=2)."""
        cc = CloudInitConfig(package_upgrade=True, packages=[])
        payload = json.loads(cc.render()[len("#cloud-config\n") :])
        assert "bootcmd" not in payload
        assert "packages" not in payload
        assert payload["package_upgrade"] is True

    def test_render_default_omits_empty_lists(self) -> None:
        """Default CloudInitConfig renders valid cloud-config with no empty-array keys."""
        payload = json.loads(CloudInitConfig().render()[len("#cloud-config\n") :])
        assert "bootcmd" not in payload
        assert "packages" not in payload

    def test_render_keeps_non_empty_lists(self) -> None:
        """Non-empty bootcmd/packages are preserved when present."""
        cc = CloudInitConfig(bootcmd=(["echo", "hi"],), packages=["vim"])
        payload = json.loads(cc.render()[len("#cloud-config\n") :])
        assert payload["bootcmd"] == [["echo", "hi"]]
        assert payload["packages"] == ["vim"]


class TestSelectProvider:
    """select_provider() sync port method."""

    def test_returns_provider_name_when_capacity_available(self) -> None:
        """Returns the selected provider name as a bare string."""
        adapter, config = _make_mock_adapter(name="provider", priority=10)
        prov = make_provisioner(
            adapters={"provider": adapter},
            configs={"provider": config},
        )

        result = prov.select_provider(["linux"], {"provider": 0})

        assert result == "provider"

    def test_returns_none_when_no_capacity(self) -> None:
        """Returns None when provider is at max_nodes."""
        adapter, config = _make_mock_adapter(name="provider", max_nodes=5)
        prov = make_provisioner(
            adapters={"provider": adapter},
            configs={"provider": config},
        )

        result = prov.select_provider(["linux"], {"provider": 5})
        assert result is None

    def test_returns_none_when_no_platform_support(self) -> None:
        """Returns None when adapter doesn't match requested platform."""
        adapter, config = _make_mock_adapter(name="provider", platform_support=False)
        prov = make_provisioner(
            adapters={"provider": adapter},
            configs={"provider": config},
        )

        result = prov.select_provider(["windows"], {"provider": 0})
        assert result is None

    def test_returns_none_when_throttled(self) -> None:
        """Returns None when op semaphore is locked."""
        adapter, config = _make_mock_adapter(name="provider")
        mock_sem = MagicMock()
        mock_sem.locked.return_value = True
        adapter.get_op_semaphore.return_value = mock_sem

        prov = make_provisioner(
            adapters={"provider": adapter},
            configs={"provider": config},
        )

        result = prov.select_provider(["linux"], {"provider": 0})
        assert result is None
