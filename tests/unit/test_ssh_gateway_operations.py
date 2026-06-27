# FILE: tests/unit/test_ssh_gateway_operations.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineOperations occupancy check + advanced operations (setup_node, get_cpu_cores, pgrep, list_processes).
#   SCOPE: occupancy_check via pgrep/check_cmd, start_occupancy_check background task, setup_node, get_cpu_cores, pgrep generator, list_processes generator.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-OPERATIONS
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestOccupancy - occupancy_check via pgrep/check_cmd, start_occupancy_check background task
#   TestAdvancedOperations - setup_node, get_cpu_cores, pgrep generator, list_processes generator
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extract occupancy + advanced ops tests from test_ssh_gateway.py for size compliance (GRACE-lite 1000-line limit).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.test_ssh_gateway import _AsyncIter, _make_state
from yascheduler.domain import Engine, EngineRepository
from yascheduler.domain.model import MachineState
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.platform.protocol import (
    ChannelOpenError,
    ProcessInfo,
)
from yascheduler.infra.ssh.repository import SSHMachineRepository

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def repository() -> SSHMachineRepository:
    return SSHMachineRepository()


@pytest.fixture
def operations(repository: SSHMachineRepository) -> SSHMachineOperations:
    return SSHMachineOperations(repository=repository)


@pytest.fixture
def mock_pengine() -> MagicMock:
    """Mock Engine for occupancy checks."""
    engine = MagicMock(spec=Engine)
    engine.name = "test_engine"
    engine.check_pname = None
    engine.check_cmd = None
    engine.check_cmd_code = 0
    engine.sleep_interval = 0.01
    return engine


# =============================================================================
# Occupancy
# =============================================================================


class TestOccupancy:
    """occupancy_check via pgrep and check_cmd, start_occupancy_check."""

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_found(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True when pgrep yields a process."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        mock_pengine.check_pname = "testproc"

        result = await operations.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_not_found(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns False when pgrep yields no process."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        mock_pengine.check_pname = "nonexistent"

        # Override adapter.pgrep to yield nothing
        state.adapter.pgrep = lambda *a, **kw: _AsyncIter([])  # type: ignore[assignment,misc]

        result = await operations.occupancy_check("10.0.0.1", mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_match(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True when check_cmd exit code matches."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0

        # Override adapter.run to return matching exit code
        async def _run_match(*args: object, **kwargs: Any) -> MagicMock:  # noqa: ANN401
            result = MagicMock()
            result.returncode = 0
            result.stdout = "active"
            result.stderr = ""
            return result

        state.adapter.run = _run_match  # type: ignore[assignment,misc]

        result = await operations.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_no_match(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns False when check_cmd exit code differs."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0

        async def _run_mismatch(*args: object, **kwargs: Any) -> MagicMock:  # noqa: ANN401
            result = MagicMock()
            result.returncode = 3  # service not running
            result.stdout = "inactive"
            result.stderr = ""
            return result

        state.adapter.run = _run_mismatch  # type: ignore[assignment,misc]

        result = await operations.occupancy_check("10.0.0.1", mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_uses_pgrep_when_both_set(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check prefers pgrep when check_pname is set even with check_cmd."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        mock_pengine.check_pname = "testproc"
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0

        # pgrep_found = True should short-circuit and return True
        result = await operations.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_no_checks_configured(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns False when neither check_pname nor check_cmd is set."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None

        result = await operations.occupancy_check("10.0.0.1", mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_ssh_failure_returns_true(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True (busy) when pgrep fails due to SSH error."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        mock_pengine.check_pname = "sleep"

        # Replace adapter.pgrep with one that raises SSHRetryExc
        async def _pgrep_ssh_fail(
            *args: object, **kwargs: object
        ) -> AsyncGenerator[None, None]:
            raise ChannelOpenError(1, "SSH connection lost")
            yield  # makes this an async generator

        state.adapter.pgrep = _pgrep_ssh_fail  # type: ignore[assignment,misc]

        result = await operations.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_ssh_failure_returns_true(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True (busy) when check_cmd fails due to SSH error."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "ps -eocomm= | grep -q sleep"
        mock_pengine.check_cmd_code = 0

        # Patch run_full to raise SSHRetryExc — simulates SSH failure
        with patch.object(
            operations,
            "run_full",
            AsyncMock(side_effect=ChannelOpenError(1, "SSH connection lost")),
        ):
            result = await operations.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_start_occupancy_check_releases_machine(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """start_occupancy_check background task releases machine when occupancy ends."""
        ip = "10.0.0.1"
        state = _make_state(ip=ip, state=MachineState.FREE)
        repository._machines[ip] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None

        with (
            patch("yascheduler.infra.ssh.repository.asyncio.sleep", AsyncMock()),
            patch.object(
                operations.occupancy, "occupancy_check", AsyncMock(return_value=False)
            ),
        ):
            operations.occupancy.start_occupancy_check(ip, mock_pengine)
            # Wait for the background task to complete
            task = repository._monitors[ip]
            await asyncio.wait_for(task, timeout=1.0)

        # Machine should be released
        assert repository._machines[ip].machine.state == MachineState.FREE

    @pytest.mark.asyncio
    async def test_start_occupancy_check_cancelled_gracefully(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """Start occupancy check then cancel it (disconnect)."""

        ip = "10.0.0.1"
        state = _make_state(ip=ip, state=MachineState.FREE)
        repository._machines[ip] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None

        with (
            patch("yascheduler.infra.ssh.repository.asyncio.sleep", AsyncMock()),
            patch.object(
                operations.occupancy,
                "occupancy_check",
                AsyncMock(side_effect=[True, True, True]),
            ),
        ):
            operations.occupancy.start_occupancy_check(ip, mock_pengine)
            # Let the task start and do one iteration
            await asyncio.sleep(0)

            # Disconnect cancels the background task
            await repository.disconnect(ip)

        # Machine removed
        assert ip not in repository


# =============================================================================
# Advanced Operations
# =============================================================================


class TestAdvancedOperations:
    """setup_node, get_cpu_cores, pgrep generator, list_processes generator."""

    @pytest.mark.asyncio
    async def test_setup_node(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """setup_node delegates to adapter.setup_node with filtered engines."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        engine_repo = MagicMock(spec=EngineRepository)
        engine_repo.filter_platforms.return_value = engine_repo

        await operations.setup_node("10.0.0.1", engine_repo)

        engine_repo.filter_platforms.assert_called_once_with(state.platforms)
        state.adapter.setup_node.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_get_cpu_cores(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """get_cpu_cores returns count from adapter."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        cores = await operations.get_cpu_cores("10.0.0.1")
        assert cores == 4

    @pytest.mark.asyncio
    async def test_pgrep_yields_processes(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """pgrep yields process info objects."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        results: list[ProcessInfo] = []
        async for proc in operations.pgrep("10.0.0.1", "testproc"):
            results.append(proc)

        assert len(results) == 1
        assert results[0].pid == 1234

    @pytest.mark.asyncio
    async def test_list_processes_yields_processes(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """list_processes yields all running processes."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        results: list[ProcessInfo] = []
        async for proc in operations.list_processes("10.0.0.1"):
            results.append(proc)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_pgrep_unknown_ip(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """pgrep raises AssertionError for unknown IP."""
        with pytest.raises(AssertionError):
            async for _ in operations.pgrep("10.0.0.99", "test"):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_list_processes_unknown_ip(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """list_processes raises AssertionError for unknown IP."""
        with pytest.raises(AssertionError):
            async for _ in operations.list_processes("10.0.0.99"):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_setup_node_unknown_ip(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """setup_node raises AssertionError for unknown IP."""
        engine_repo = MagicMock(spec=EngineRepository)
        with pytest.raises(AssertionError):
            await operations.setup_node("10.0.0.99", engine_repo)

    @pytest.mark.asyncio
    async def test_get_cpu_cores_unknown_ip(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """get_cpu_cores raises AssertionError for unknown IP."""
        with pytest.raises(AssertionError):
            await operations.get_cpu_cores("10.0.0.99")
