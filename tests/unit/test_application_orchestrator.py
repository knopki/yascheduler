# FILE: tests/unit/test_application_orchestrator.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for Orchestrator lifecycle management after v2.0.0 extraction.
#   SCOPE: Constructor queue initialization, start/stop lifecycle, cancellation propagation, concurrency limits.
#   DEPENDS: M-APPLICATION-ORCHESTRATOR
#   LINKS: M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestOrchestratorLifecycle - Lifecycle: constructor queues, start tasks, stop cleanup, cancellation, limits
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Update to uow_factory constructor; remove db parameter.
#   PREVIOUS_CHANGE: v1.1.0 - Add deallocate_limit concurrency test; update call_count for 4 producer-consumer loops.
#   PREVIOUS_CHANGE: v1.0.0 - Initial Orchestrator unit tests.
# END_CHANGE_SUMMARY
#
"""Unit tests for Orchestrator lifecycle management.

Tests cover:
- Constructor creates 4 UniqueQueues with correct names
- Start lifecycle creates all 5 background tasks
- Stop lifecycle cancels tasks, calls cleanup on clouds/remote_machines/http
- Cancellation propagation to producer-consumer loops
- Concurrency limits (allocate_limit, deallocate_limit) passed through to _create_producer_consumers
"""

import asyncio
from collections import Counter
from collections.abc import AsyncGenerator
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.application.orchestrator import Orchestrator
from yascheduler.application.uow import AbstractUnitOfWork
from yascheduler.config import (
    Config,
    ConfigDb,
    ConfigLocal,
    ConfigRemote,
    Engine,
    EngineRepository,
)
from yascheduler.domain.events import TaskAbandoned
from yascheduler.domain.model import Task, TaskContext, TaskStatus
from yascheduler.queue import UniqueQueue

# =============================================================================
# Helpers
# =============================================================================


def create_mock_config(
    allocate_limit: int = 3,
    consume_limit: int = 2,
    conn_machine_limit: int = 1,
    deallocate_limit: int = 1,
) -> MagicMock:
    """Create a mocked Config with local/remote sub-configs."""
    local = MagicMock(spec=ConfigLocal)
    local.conn_machine_pending = 10
    local.allocate_pending = 5
    local.consume_pending = 3
    local.deallocate_pending = 2
    local.webhook_reqs_limit = 5
    local.conn_machine_limit = conn_machine_limit
    local.allocate_limit = allocate_limit
    local.consume_limit = consume_limit
    local.deallocate_limit = deallocate_limit

    remote = MagicMock(spec=ConfigRemote)
    remote.tasks_dir = PurePosixPath("/tmp/tasks")
    remote.data_dir = PurePosixPath("/tmp/data")
    remote.engines_dir = PurePosixPath("/tmp/engines")
    remote.username = "root"

    config = MagicMock(spec=Config)
    config.local = local
    config.remote = remote
    config.clouds = []
    config.db = MagicMock(spec=ConfigDb)

    return config


def make_orchestrator(
    allocate_limit: int = 3,
    consume_limit: int = 2,
    conn_machine_limit: int = 1,
    deallocate_limit: int = 1,
    sleep_interval: int = 0,
) -> Orchestrator:
    """Create an Orchestrator with all dependencies mocked.

    Uses a real Engine with sleep_interval=0 so asleep_until calls
    return immediately, keeping tests fast.
    """
    config = create_mock_config(
        allocate_limit=allocate_limit,
        consume_limit=consume_limit,
        conn_machine_limit=conn_machine_limit,
        deallocate_limit=deallocate_limit,
    )

    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)

    def uow_factory() -> AbstractUnitOfWork:
        return mock_uow

    clouds = AsyncMock()
    gateway = MagicMock()
    gateway.__len__ = MagicMock(return_value=1)
    gateway.disconnect_all = AsyncMock()

    # EngineRepository.values() must yield at least one Engine so
    # Orchestrator.__init__ can compute min(sleep_interval).
    engine = MagicMock(spec=Engine, sleep_interval=sleep_interval)
    engines = MagicMock(spec=EngineRepository)
    engines.values.return_value = [engine]

    log = MagicMock()

    orch = Orchestrator(
        config=config,
        uow_factory=uow_factory,
        clouds=clouds,
        gateway=gateway,
        engines=engines,
        log=log,
        config_clouds=[],
        local_tasks_dir=Path("/tmp"),
    )
    return orch


# =============================================================================
# Tests
# =============================================================================


class TestOrchestratorLifecycle:
    """Orchestrator lifecycle: constructor, start, stop, cancellation, limits."""

    # ------------------------------------------------------------------ #
    # Test 1: constructor creates 4 queues
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_orchestrator_constructor_initializes_queues(self) -> None:
        """Orchestrator __init__ creates 4 UniqueQueues with correct names."""
        orch = make_orchestrator()
        assert orch._conn_machine_q.name == "conn_machine"
        assert orch._allocate_q.name == "allocate"
        assert orch._consume_q.name == "consume"
        assert orch._deallocate_q.name == "deallocate"

    # ------------------------------------------------------------------ #
    # Test 2: start creates all background tasks
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_start_creates_background_tasks(self) -> None:
        """start() creates 5 background tasks for stats and all loops."""
        orch = make_orchestrator()

        # Pre-set cancellation so loops exit immediately instead of
        # blocking on asleep_until or waiting for queue items.
        orch._cancellation_event.set()
        # wait_some_machines needs at least one connected machine to
        # exit instantly instead of waiting up to 30 s.
        orch._gateway.__len__ = MagicMock(return_value=1)  # type: ignore[attr-defined,method-assign]

        with patch(
            "yascheduler.application.orchestrator.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await orch.start()

        assert len(orch._bg_jobs) == 5

    # ------------------------------------------------------------------ #
    # Test 3: stop cancels tasks and calls cleanup
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks_and_cleans_up(self) -> None:
        """stop() sets cancellation_event, cancels tasks, cleans up resources."""
        orch = make_orchestrator()

        # Create real asyncio Tasks that never complete on their own.
        async def _never_end() -> None:
            await asyncio.Event().wait()

        task1 = asyncio.create_task(_never_end())
        task2 = asyncio.create_task(_never_end())
        orch._bg_jobs = {task1, task2}

        await orch.stop()

        # Cancellation event signalled
        assert orch._cancellation_event.is_set()

        # All background tasks cancelled
        assert task1.cancelled()
        assert task2.cancelled()

        # Cleanup methods called
        orch._clouds.stop.assert_called_once()  # type: ignore[attr-defined]
        orch._gateway.disconnect_all.assert_called_once()  # type: ignore[attr-defined]
        # _http lifecycle owned by start()'s finally block, not stop()

    # ------------------------------------------------------------------ #
    # Test 4: cancellation propagates to the producer-consumer loop
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_cancellation_propagates_to_producer_consumer_loop(self) -> None:
        """cancellation_event set before loop start causes immediate exit.

        The producer-consumer loop checks ``self._cancellation_event.is_set()``
        at the top of its while-condition.  When pre-set, the loop exits
        without processing any items.
        """
        orch = make_orchestrator(sleep_interval=0)

        q: UniqueQueue = UniqueQueue("test", maxsize=10)

        async def empty_producer() -> AsyncGenerator[None, None]:
            """Yields nothing — a no-op async generator."""
            return
            yield  # pragma: no cover  # type: ignore[unreachable]

        consumer = AsyncMock()

        # Pre-set cancellation so the while-condition fails immediately
        orch._cancellation_event.set()

        await orch._create_producer_consumers(
            q, empty_producer, consumer, workers_num=2
        )

        # No items were ever produced since the loop never entered its body
        consumer.assert_not_called()
        assert q.empty()

    # ------------------------------------------------------------------ #
    # Test 5: concurrency limits (allocate_limit) respected
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_concurrency_limits_allocate_limit(self) -> None:
        """allocate_limit config value is passed as workers_num to _create_producer_consumers."""
        orch = make_orchestrator(allocate_limit=3)

        orch._cancellation_event.set()
        orch._gateway.__len__ = MagicMock(return_value=1)  # type: ignore[attr-defined,method-assign]

        with patch.object(
            orch,
            "_create_producer_consumers",
            wraps=orch._create_producer_consumers,
        ) as mock_pc:
            with patch(
                "yascheduler.application.orchestrator.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                await orch.start()

        # _create_producer_consumers is called 4 times (conn_machine / allocate / consume / deallocate)
        assert mock_pc.call_count == 4

        # Second call is for the allocate queue
        allocate_call = mock_pc.call_args_list[1]
        assert allocate_call.kwargs["queue"] is orch._allocate_q
        assert allocate_call.kwargs["workers_num"] == 3

    # ------------------------------------------------------------------ #
    # Test 6: concurrency limits (deallocate_limit) respected
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_concurrency_limits_deallocate_limit(self) -> None:
        """deallocate_limit config value is passed as workers_num to _create_producer_consumers."""
        orch = make_orchestrator(deallocate_limit=5)

        orch._cancellation_event.set()
        orch._gateway.__len__ = MagicMock(return_value=1)  # type: ignore[attr-defined,method-assign]

        with patch.object(
            orch,
            "_create_producer_consumers",
            wraps=orch._create_producer_consumers,
        ) as mock_pc:
            with patch(
                "yascheduler.application.orchestrator.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                await orch.start()

        # Fourth call is for the deallocate queue
        deallocate_call = mock_pc.call_args_list[3]
        assert deallocate_call.kwargs["queue"] is orch._deallocate_q
        assert deallocate_call.kwargs["workers_num"] == 5

    # ------------------------------------------------------------------ #
    # Test 7: concurrency limits (conn_machine_limit) respected
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_concurrency_limits_conn_machine_limit(self) -> None:
        """conn_machine_limit config value is passed as workers_num to _create_producer_consumers."""
        orch = make_orchestrator(conn_machine_limit=4)

        orch._cancellation_event.set()
        orch._gateway.__len__ = MagicMock(return_value=1)  # type: ignore[attr-defined,method-assign]

        with patch.object(
            orch,
            "_create_producer_consumers",
            wraps=orch._create_producer_consumers,
        ) as mock_pc:
            with patch(
                "yascheduler.application.orchestrator.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                await orch.start()

        # First call is for the conn_machine queue
        conn_machine_call = mock_pc.call_args_list[0]
        assert conn_machine_call.kwargs["queue"] is orch._conn_machine_q
        assert conn_machine_call.kwargs["workers_num"] == 4

    # ------------------------------------------------------------------ #
    # Test 8: concurrency limits (consume_limit) respected
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_concurrency_limits_consume_limit(self) -> None:
        """consume_limit config value is passed as workers_num to _create_producer_consumers."""
        orch = make_orchestrator(consume_limit=7)

        orch._cancellation_event.set()
        orch._gateway.__len__ = MagicMock(return_value=1)  # type: ignore[attr-defined,method-assign]

        with patch.object(
            orch,
            "_create_producer_consumers",
            wraps=orch._create_producer_consumers,
        ) as mock_pc:
            with patch(
                "yascheduler.application.orchestrator.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                await orch.start()

        # Third call is for the consume queue
        consume_call = mock_pc.call_args_list[2]
        assert consume_call.kwargs["queue"] is orch._consume_q
        assert consume_call.kwargs["workers_num"] == 7


class TestOrchestratorTaskAbandoned:
    """Test that TaskAbandoned event is recorded when machine is gone."""

    async def test_machine_gone_records_task_abandoned_event(self) -> None:
        """When a machine is gone for > broken_tasks_passes cycles, TaskAbandoned is recorded."""
        from yascheduler.queue import UMessage

        orch = make_orchestrator()

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        orch._uow_factory = uow_factory  # type: ignore[method-assign]

        # Gateway returns None for machine state (machine gone)
        orch._gateway.get_machine_state = MagicMock(return_value=None)  # type: ignore[method-assign]

        task = Task(
            task_id=42,
            label="test",
            context=TaskContext(
                engine="test_engine",
                webhook_url="https://hook.example.com",
                webhook_custom_params={"k": "v"},
            ),
            status=TaskStatus.RUNNING,
            allocated_ip="10.0.0.1",
        )
        msg = UMessage(42, task)
        machine_not_found: Counter[str] = Counter()

        # First call: counter is 1, not enough yet
        await orch._task_consumer_consumer(msg, machine_not_found)
        assert machine_not_found[42] == 1  # type: ignore[index]
        uow.tasks.save.assert_not_called()

        # Call enough times to exceed broken_tasks_passes (20)
        machine_not_found[42] = 21  # type: ignore[index]
        await orch._task_consumer_consumer(msg, machine_not_found)

        # save should have been called with a task that has TaskAbandoned event
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error == "node is gone"
        assert len(saved_task._events) == 1
        event = saved_task._events[0]
        assert isinstance(event, TaskAbandoned)
        assert event.task_id == 42
        assert event.node_ip == "10.0.0.1"
        assert event.webhook_url == "https://hook.example.com"
        assert event.webhook_custom_params == {"k": "v"}
        uow.commit.assert_called_once()
