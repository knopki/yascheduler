# FILE: tests/unit/test_daemon_common_cleanup.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for run_daemon's try/finally cleanup guarantee (fix-daemon-resource-leak-on-start-return).
#   SCOPE: orch.stop() runs on every exit path — normal start() return, start() raising, signal-then-finally no-op,
#          and make_daemon success + start() raising still cleans up early bg jobs. make_daemon is mocked.
#   DEPENDS: M-DAEMON-COMMON
#   LINKS: M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _make_real_orchestrator - Build a real Orchestrator with mocked deps + injectable start/http_session
#   _capture_signal_handlers - override loop.add_signal_handler to record SIGTERM/SIGINT handler callables
#   TestStartReturnsNormallyCallsStop - start() returns normally -> finally calls stop() once
#   TestStartRaisesStillCallsStop - start() raises -> finally still calls stop(), exception propagates
#   TestSignalHandlerThenFinallyIsNoop - signal handler runs stop() first; finally's stop() is a no-op
#   TestMakeDaemonStartRaisesCleansEarlyJobs - finally's stop() cancels early bg jobs + closes http_session
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial tests for run_daemon try/finally cleanup guarantee (fix-daemon-resource-leak-on-start-return).
# END_CHANGE_SUMMARY
"""Unit tests for run_daemon's try/finally cleanup guarantee."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.orchestrator import Orchestrator
from yascheduler.domain import Engine, EngineRepository, LocalSettings, RemoteDefaults
from yascheduler.entrypoints import Config
from yascheduler.entrypoints.cli import daemon_common

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    """Snapshot/restore the root logger so handler additions don't leak across tests."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    try:
        yield
    finally:
        root.setLevel(original_level)
        root.handlers = list(original_handlers)


def _make_real_orchestrator(
    http_session: MagicMock,
    clouds_stop: AsyncMock | None = None,
    disconnect_all: AsyncMock | None = None,
) -> Orchestrator:
    """Build a real Orchestrator with mocked deps so stop() exercises the real
    idempotent/exception-safe cleanup path. ``start`` is monkeypatched per-test."""
    local = MagicMock(spec=LocalSettings)
    local.conn_machine_pending = 10
    local.allocate_pending = 5
    local.consume_pending = 3
    local.deallocate_pending = 2
    local.conn_machine_limit = 1
    local.allocate_limit = 1
    local.consume_limit = 1
    local.deallocate_limit = 1

    remote = MagicMock(spec=RemoteDefaults)
    remote.tasks_dir = PurePosixPath("/tmp/tasks")
    remote.data_dir = PurePosixPath("/tmp/data")
    remote.engines_dir = PurePosixPath("/tmp/engines")
    remote.username = "root"

    config = MagicMock(spec=Config)
    config.local = local
    config.remote = remote

    engine = MagicMock(spec=Engine, sleep_interval=0)
    engine.name = "test_engine"
    engines = MagicMock(spec=EngineRepository)
    engines.values.return_value = [engine]

    clouds = MagicMock()
    clouds.stop = clouds_stop if clouds_stop is not None else AsyncMock()

    repository = MagicMock()
    repository.__len__ = MagicMock(return_value=0)
    repository.disconnect_all = (
        disconnect_all if disconnect_all is not None else AsyncMock()
    )
    task_deployer = MagicMock()
    output_downloader = MagicMock()
    occupancy_checker = MagicMock()

    return Orchestrator(
        local_settings=local,
        remote_defaults=remote,
        uow_factory=lambda: AsyncMock(),
        clouds=clouds,
        repository=repository,
        task_deployer=task_deployer,
        output_downloader=output_downloader,
        occupancy_checker=occupancy_checker,
        engines=engines,
        log=MagicMock(spec=logging.Logger),
        config_clouds=[],
        local_tasks_dir=MagicMock(),  # type: ignore[arg-type]
        allocation_tracker=AllocationTracker(),
        active_clouds=[],
        allocation_lock=asyncio.Lock(),
        list_private_keys_fn=lambda _keys_dir: [],
        http_session=http_session,
    )


def _capture_signal_handlers(
    loop: asyncio.AbstractEventLoop,
) -> dict[signal.Signals, Callable[[], object]]:
    """Override loop.add_signal_handler so SIGTERM/SIGINT registrations are captured
    as zero-arg callables (each returns a task wrapping on_signal)."""
    registered: dict[signal.Signals, Callable[[], object]] = {}

    def fake_add_signal_handler(sig: object, handler: object, *args: object) -> None:
        registered[signal.Signals(sig)] = handler  # type: ignore[index,assignment]

    object.__setattr__(loop, "add_signal_handler", fake_add_signal_handler)
    return registered


# =============================================================================
# 5.2: start() returns normally -> finally calls stop() once
# =============================================================================


class TestStartReturnsNormallyCallsStop:
    async def test_start_returns_normally_calls_stop(self) -> None:
        orch = MagicMock()
        orch.start = AsyncMock()
        orch.stop = AsyncMock()
        daemon_common.make_daemon = AsyncMock(return_value=orch)  # type: ignore[assignment]

        await daemon_common.run_daemon(MagicMock(), logging.getLogger("t"))

        orch.start.assert_awaited_once()
        # finally's stop() ran once (no signal arrived).
        orch.stop.assert_awaited_once()


# =============================================================================
# 5.3: start() raises -> finally still calls stop(); exception propagates
# =============================================================================


class TestStartRaisesStillCallsStop:
    async def test_start_raises_still_calls_stop(self) -> None:
        orch = MagicMock()
        orch.start = AsyncMock(side_effect=RuntimeError("start boom"))
        orch.stop = AsyncMock()
        daemon_common.make_daemon = AsyncMock(return_value=orch)  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="start boom"):
            await daemon_common.run_daemon(MagicMock(), logging.getLogger("t"))

        orch.start.assert_awaited_once()
        # finally's stop() ran despite the exception.
        orch.stop.assert_awaited_once()


# =============================================================================
# 5.4: signal handler runs stop() first; finally's stop() is a no-op
# =============================================================================


class TestSignalHandlerThenFinallyIsNoop:
    async def test_signal_handler_then_finally_is_noop(self) -> None:
        # START_BLOCK_TEST_SIGNAL_HANDLER_THEN_FINALLY_IS_NOOP
        # Use a real Orchestrator so its _stopped guard makes the second
        # stop() call a genuine no-op (rather than a hand-rolled simulation).
        clouds_stop = AsyncMock()
        disconnect_all = AsyncMock()
        http_session = MagicMock()
        http_session.close = AsyncMock()
        orch = _make_real_orchestrator(
            http_session=http_session,
            clouds_stop=clouds_stop,
            disconnect_all=disconnect_all,
        )

        # Capture handlers BEFORE run_daemon registers them.
        handlers = _capture_signal_handlers(asyncio.get_running_loop())

        async def _start() -> None:
            # Simulate SIGTERM arriving mid-start(): fire the registered handler.
            # The handler is a zero-arg callable that internally creates its own task
            # and returns it; capture it so we can cancel the handler's trailing
            # `await asyncio.sleep(0.25)` before the test ends (avoids a
            # "Task was destroyed but it is pending!" teardown warning).
            sig_task = handlers[signal.SIGTERM]()
            # Let the signal-handler's stop() run to completion before start() returns.
            for _ in range(4):
                await asyncio.sleep(0)
            # The handler then sleeps 250ms (SSL grace); cancel that pending sleep
            # so pytest-asyncio teardown doesn't destroy a pending task.
            assert isinstance(sig_task, asyncio.Task)
            sig_task.cancel()
            try:
                await sig_task
            except asyncio.CancelledError:
                pass

        orch.start = _start  # type: ignore[method-assign]
        daemon_common.make_daemon = AsyncMock(return_value=orch)  # type: ignore[assignment]

        await daemon_common.run_daemon(MagicMock(), logging.getLogger("t"))

        # stop() cleanup body (http_session.close) ran exactly once: the
        # signal-handler's call ran the body; the finally's call was a no-op.
        http_session.close.assert_awaited_once()
        clouds_stop.assert_awaited_once()
        disconnect_all.assert_awaited_once()
        assert orch._stopped is True
        assert orch._http_session is None
        # END_BLOCK_TEST_SIGNAL_HANDLER_THEN_FINALLY_IS_NOOP


# =============================================================================
# 5.5: make_daemon success + start() raises -> finally cleans early jobs + http_session
# =============================================================================


class TestMakeDaemonStartRaisesCleansEarlyJobs:
    async def test_make_daemon_success_start_raises_cleans_early_jobs(self) -> None:
        # START_BLOCK_TEST_MAKE_DAEMON_SUCCESS_START_RAISES_CLEANS_EARLY_JOBS
        # Real Orchestrator: start() raises after an early bg job is registered,
        # and the finally's stop() must cancel that job and close http_session.
        clouds_stop = AsyncMock()
        disconnect_all = AsyncMock()
        http_session = MagicMock()
        http_session.close = AsyncMock()
        orch = _make_real_orchestrator(
            http_session=http_session,
            clouds_stop=clouds_stop,
            disconnect_all=disconnect_all,
        )

        async def _early_job() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise

        early_task = asyncio.create_task(_early_job())
        orch._bg_jobs.add(early_task)

        async def _start_that_raises() -> None:
            # Mimic start() adding _print_stats then blowing up before the barrier.
            raise RuntimeError("start boom after early jobs")

        orch.start = _start_that_raises  # type: ignore[method-assign]
        daemon_common.make_daemon = AsyncMock(return_value=orch)  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="start boom after early jobs"):
            await daemon_common.run_daemon(MagicMock(), logging.getLogger("t"))

        # finally's stop() cancelled the early job and closed the http_session.
        assert early_task.done()
        assert orch._http_session is None
        http_session.close.assert_awaited_once()
        clouds_stop.assert_awaited_once()
        disconnect_all.assert_awaited_once()
        # END_BLOCK_TEST_MAKE_DAEMON_SUCCESS_START_RAISES_CLEANS_EARLY_JOBS
