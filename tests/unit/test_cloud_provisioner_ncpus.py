# FILE: tests/unit/test_cloud_provisioner_ncpus.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for CloudProvisionerImpl ncpus semantics — no write-back, None-safe DONE log.
#   SCOPE: allocate/_setup_vm ncpus behavior with all provider SDKs and SSHMachineGateway mocked (no DB).
#   DEPENDS: M-CLOUD-PROVISIONER, M-DOMAIN-MODEL
#   LINKS: M-CLOUD-PROVISIONER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestAllocateNcpus - allocate does not write ncpus onto Node; DONE log is None-safe
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - node-ncpus-as-config: extract ncpus-related allocate tests from test_cloud_provisioner_impl.py (file over 1000-line hard limit).
# END_CHANGE_SUMMARY


from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.test_cloud_provisioner_impl import (
    _make_mock_adapter,
    _make_mock_repository,
    _tmp_node,
    make_provisioner,
)
from yascheduler.domain.model import Node


@pytest.fixture
def mock_engines() -> MagicMock:
    """Create mock EngineRepository with filter chain."""
    eng = MagicMock()
    eng.filter.return_value = eng
    eng.get_platform_packages.return_value = ["vim", "htop"]
    return eng


@pytest.fixture
def mock_local_config() -> MagicMock:
    """Create mock LocalSettings with fake keys_dir."""
    cfg = MagicMock()
    mock_keys_dir = MagicMock(spec=Path)
    mock_keys_dir.iterdir.return_value = []
    cfg.keys_dir = mock_keys_dir
    return cfg


class TestAllocateNcpus:
    """allocate() ncpus semantics: no write-back, None-safe DONE log."""

    @pytest.mark.asyncio
    async def test_setup_vm_does_not_write_ncpus(
        self,
        mock_engines: MagicMock,
        mock_local_config: MagicMock,
    ) -> None:
        """Node.ncpus is None after allocate; get_cpu_cores not called inside _setup_vm."""
        adapter, config = _make_mock_adapter(name="test", priority=10)
        sessions: list[MagicMock] = []

        async def _connect(**kw: Any) -> MagicMock:
            machine = MagicMock()
            machine.hostname = kw["node"].hostname
            machine.run = AsyncMock(
                return_value=MagicMock(exit_code=0, stdout="", stderr=""),
            )
            machine.setup_node = AsyncMock()
            machine.get_cpu_cores = AsyncMock(return_value=4)
            sessions.append(machine)
            return machine

        repo = MagicMock()
        repo.connect = _connect
        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            machine_repository=repo,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        with patch(
            "yascheduler.infra.cloud.manager.CloudProvisionerImpl._get_ssh_key",
            new=AsyncMock(return_value=MagicMock()),
        ):
            node = await prov.allocate("test", _tmp_node(999))

        assert isinstance(node, Node)
        assert node.ncpus is None
        assert len(sessions) == 1
        sessions[0].get_cpu_cores.assert_not_called()

    @pytest.mark.asyncio
    async def test_allocate_done_log_is_none_safe_for_ncpus(
        self,
        mock_engines: MagicMock,
        mock_local_config: MagicMock,
    ) -> None:
        """DONE log formats ncpus=None with %s — no TypeError."""
        adapter, config = _make_mock_adapter(name="test", priority=10)
        repo = _make_mock_repository()

        prov = make_provisioner(
            adapters={"test": adapter},
            configs={"test": config},
            machine_repository=repo,
            engines=mock_engines,
            local_config=mock_local_config,
        )

        with patch(
            "yascheduler.infra.cloud.manager.CloudProvisionerImpl._get_ssh_key",
            new=AsyncMock(return_value=MagicMock()),
        ):
            node = await prov.allocate("test", _tmp_node(999))

        assert node.ncpus is None
