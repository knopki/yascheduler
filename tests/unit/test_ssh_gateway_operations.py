# FILE: tests/unit/test_ssh_gateway_operations.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineOperations occupancy check + advanced operations (setup_node, get_cpu_cores) via the session-typed facade.
#   SCOPE: occupancy_check via pgrep/check_cmd, start_occupancy_check background task, setup_node, get_cpu_cores.
#   DEPENDS: M-SSH-OPERATIONS, M-SSH-SESSION
#   LINKS: M-SSH-OPERATIONS, M-SSH-SESSION
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestOccupancy - occupancy_check via pgrep/check_cmd, start_occupancy_check background task
#   TestAdvancedOperations - setup_node, get_cpu_cores (facade delegates to session)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - session-based-machine-handle: operations facade takes session instead of ip/machine. Removed pgrep/list_processes/unknown-IP tests (those primitives now live on the session and the facade no longer IP-keys). start_occupancy_check patch target moves from repository.asyncio.sleep to session.asyncio.sleep; monitor task accessed via session._monitor_task.
#   PREVIOUS_CHANGE: v1.0.0 - Extract occupancy + advanced ops tests from test_ssh_gateway.py for size compliance (GRACE-lite 1000-line limit).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.test_ssh_gateway import _AsyncIter, _make_state
from yascheduler.domain import Engine, EngineRepository
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.platform.protocol import ChannelOpenError
from yascheduler.infra.ssh.repository import SSHMachineRepository

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
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True when pgrep yields a process."""
        session = _make_state()
        mock_pengine.check_pname = "testproc"
        result = await operations.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_not_found(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns False when pgrep yields no process."""
        session = _make_state()
        mock_pengine.check_pname = "nonexistent"
        # Override adapter.pgrep to yield nothing
        session._adapter.pgrep = lambda *a, **kw: _AsyncIter([])  # type: ignore[assignment,misc]  # noqa: SLF001
        result = await operations.occupancy_check(session, mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_match(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True when check_cmd exit code matches."""
        session = _make_state()
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0

        async def _run_match(*args: object, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "active"
            result.stderr = ""
            return result

        session._adapter.run = _run_match  # type: ignore[assignment,misc]  # noqa: SLF001

        result = await operations.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_no_match(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns False when check_cmd exit code differs."""
        session = _make_state()
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0

        async def _run_mismatch(*args: object, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 3
            result.stdout = "inactive"
            result.stderr = ""
            return result

        session._adapter.run = _run_mismatch  # type: ignore[assignment,misc]  # noqa: SLF001

        result = await operations.occupancy_check(session, mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_uses_pgrep_when_both_set(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check prefers pgrep when check_pname is set even with check_cmd."""
        session = _make_state()
        mock_pengine.check_pname = "testproc"
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0
        result = await operations.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_no_checks_configured(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns False when neither check_pname nor check_cmd is set."""
        session = _make_state()
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None
        result = await operations.occupancy_check(session, mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_ssh_failure_returns_true(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True (busy) when pgrep fails due to SSH error."""
        session = _make_state()
        mock_pengine.check_pname = "sleep"

        # Replace adapter.pgrep with one that raises SSHRetryExc-class (ChannelOpenError)
        async def _pgrep_ssh_fail(  # noqa: ANN202
            *args: object, **kwargs: object
        ):  # type: ignore[return-type]
            raise ChannelOpenError(1, "SSH connection lost")
            yield  # type: ignore[unreachable]  # makes this an async generator

        session._adapter.pgrep = _pgrep_ssh_fail  # type: ignore[assignment,misc]  # noqa: SLF001

        result = await operations.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_ssh_failure_returns_true(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True (busy) when check_cmd fails due to SSH error."""
        session = _make_state()
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "ps -eocomm= | grep -q sleep"
        mock_pengine.check_cmd_code = 0

        # Patch session.run_full to raise ChannelOpenError — simulates SSH failure.
        with patch.object(
            session,
            "run_full",
            AsyncMock(side_effect=ChannelOpenError(1, "SSH connection lost")),
        ):
            result = await operations.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_start_occupancy_check_releases_machine(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """start_occupancy_check background task releases machine when occupancy ends."""
        from yascheduler.domain.model import MachineState

        session = _make_state(state=MachineState.FREE)
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None

        with (
            patch("yascheduler.infra.ssh.session.asyncio.sleep", AsyncMock()),
            patch.object(
                operations.occupancy, "occupancy_check", AsyncMock(return_value=False)
            ),
        ):
            operations.occupancy.start_occupancy_check(session, mock_pengine)
            task = session._monitor_task  # noqa: SLF001
            assert task is not None
            await asyncio.wait_for(task, timeout=1.0)

        # Session should be released
        assert session.machine.state == MachineState.FREE

    @pytest.mark.asyncio
    async def test_start_occupancy_check_cancelled_gracefully(
        self,
        operations: SSHMachineOperations,
        mock_pengine: MagicMock,
    ) -> None:
        """Start occupancy check then cancel it (disconnect cancels monitor via _close)."""

        from yascheduler.domain.model import MachineState

        session = _make_state(state=MachineState.FREE)
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None

        with (
            patch("yascheduler.infra.ssh.session.asyncio.sleep", AsyncMock()),
            patch.object(
                operations.occupancy,
                "occupancy_check",
                AsyncMock(side_effect=[True, True, True]),
            ),
        ):
            operations.occupancy.start_occupancy_check(session, mock_pengine)
            await asyncio.sleep(0)

            # _close cancels the monitor task
            await session._close()  # noqa: SLF001

        assert session.is_closed is True


# =============================================================================
# Advanced Operations (facade delegates to session)
# =============================================================================


class TestAdvancedOperations:
    """setup_node, get_cpu_cores via the operations facade."""

    @pytest.mark.asyncio
    async def test_setup_node(self, operations: SSHMachineOperations) -> None:
        """setup_node delegates to session.setup_node (adapter.setup_node with filtered engines)."""
        session = _make_state()
        engine_repo = MagicMock(spec=EngineRepository)
        engine_repo.filter_platforms.return_value = engine_repo

        await operations.setup_node(session, engine_repo)

        engine_repo.filter_platforms.assert_called_once_with(session.platforms)
        session._adapter.setup_node.assert_awaited_once()  # type: ignore[attr-defined]  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_get_cpu_cores(self, operations: SSHMachineOperations) -> None:
        """get_cpu_cores returns count from session (adapter)."""
        session = _make_state()
        cores = await operations.get_cpu_cores(session)
        assert cores == 4
