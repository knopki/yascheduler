# region MODULE_CONTRACT
# PURPOSE: Unit tests for OccupancyChecker — occupancy check via pgrep/check_cmd, start_occupancy_check background task.
# SCOPE: occupancy_check via pgrep/check_cmd, start_occupancy_check background task.
# KEYWORDS: OccupancyChecker, pgrep, check_cmd, occupancy check
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.test_ssh_gateway import _AsyncIter, _make_state
from yascheduler.domain import Engine
from yascheduler.infra.ssh.operations import OccupancyChecker
from yascheduler.infra.ssh.platform.types import ChannelOpenError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def occupancy_checker() -> OccupancyChecker:
    return OccupancyChecker()


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
        occupancy_checker: OccupancyChecker,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True when pgrep yields a process."""
        session = _make_state()
        mock_pengine.check_pname = "testproc"
        result = await occupancy_checker.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_not_found(
        self,
        occupancy_checker: OccupancyChecker,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns False when pgrep yields no process."""
        session = _make_state()
        mock_pengine.check_pname = "nonexistent"
        # Override adapter.pgrep to yield nothing
        session._adapter.pgrep = lambda *a, **kw: _AsyncIter([])  # type: ignore[assignment,misc]
        result = await occupancy_checker.occupancy_check(session, mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_match(
        self,
        occupancy_checker: OccupancyChecker,
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

        session._adapter.run = _run_match  # type: ignore[assignment,misc]

        result = await occupancy_checker.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_no_match(
        self,
        occupancy_checker: OccupancyChecker,
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

        session._adapter.run = _run_mismatch  # type: ignore[assignment,misc]

        result = await occupancy_checker.occupancy_check(session, mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_uses_pgrep_when_both_set(
        self,
        occupancy_checker: OccupancyChecker,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check prefers pgrep when check_pname is set even with check_cmd."""
        session = _make_state()
        mock_pengine.check_pname = "testproc"
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0
        result = await occupancy_checker.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_no_checks_configured(
        self,
        occupancy_checker: OccupancyChecker,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns False when neither check_pname nor check_cmd is set."""
        session = _make_state()
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None
        result = await occupancy_checker.occupancy_check(session, mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_ssh_failure_returns_true(
        self,
        occupancy_checker: OccupancyChecker,
        mock_pengine: MagicMock,
    ) -> None:
        """occupancy_check returns True (busy) when pgrep fails due to SSH error."""
        session = _make_state()
        mock_pengine.check_pname = "sleep"

        # Replace adapter.pgrep with one that raises SSHRetryExc-class (ChannelOpenError)
        async def _pgrep_ssh_fail(
            *args: object,
            **kwargs: object,
        ):  # type: ignore[return-type]
            raise ChannelOpenError(1, "SSH connection lost")
            yield  # type: ignore[unreachable]  # makes this an async generator

        session._adapter.pgrep = _pgrep_ssh_fail  # type: ignore[assignment,misc]

        result = await occupancy_checker.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_ssh_failure_returns_true(
        self,
        occupancy_checker: OccupancyChecker,
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
            result = await occupancy_checker.occupancy_check(session, mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_start_occupancy_check_releases_machine(
        self,
        occupancy_checker: OccupancyChecker,
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
                occupancy_checker,
                "occupancy_check",
                AsyncMock(return_value=False),
            ),
        ):
            occupancy_checker.start_occupancy_check(session, mock_pengine)
            task = session._monitor_task
            assert task is not None
            await asyncio.wait_for(task, timeout=1.0)

        # Session should be released
        assert session.machine.state == MachineState.FREE

    @pytest.mark.asyncio
    async def test_start_occupancy_check_cancelled_gracefully(
        self,
        occupancy_checker: OccupancyChecker,
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
                occupancy_checker,
                "occupancy_check",
                AsyncMock(side_effect=[True, True, True]),
            ),
        ):
            occupancy_checker.start_occupancy_check(session, mock_pengine)
            await asyncio.sleep(0)

            # _close cancels the monitor task
            await session._close()

        assert session.is_closed is True
