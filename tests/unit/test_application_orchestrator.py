# FILE: tests/unit/test_application_orchestrator.py
# VERSION: 1.4.1
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for Orchestrator lifecycle management after v2.0.0 extraction.
#   SCOPE: Constructor queue initialization, start/stop lifecycle, cancellation propagation, concurrency limits,
#          _clouds_get_capacity inline UoW arithmetic, constructor stores allocation_tracker/active_clouds/allocation_lock,
#          _deallocator_consumer passes uow_factory to deallocate_node, _allocator_consumer swallows exceptions.
#   DEPENDS: M-APPLICATION-ORCHESTRATOR
#   LINKS: M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestOrchestratorLifecycle - Lifecycle: constructor queues, start tasks, stop cleanup, cancellation, limits
#   TestOrchestratorTaskAbandoned - TaskAbandoned event recorded when machine is gone
#   TestCloudsGetCapacity - _clouds_get_capacity inline UoW arithmetic over active_clouds
#   TestOrchestratorConstructor - Constructor stores allocation_tracker, active_clouds, allocation_lock; no _adapters/_configs
#   TestDeallocatorConsumer - _deallocator_consumer calls deallocate_node with uow_factory
#   TestAllocatorConsumer - _allocator_consumer swallows allocate_task exceptions to keep worker alive
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: [v1.5.0 - Migrate imports: ConfigDb→PostgresDbConfig, ConfigLocal→LocalSettings, ConfigRemote→RemoteDefaults; Orchestrator __init__ signature change: config=config → local_settings=config.local, remote_defaults=config.remote (config-aggregate-to-entrypoints / P4).]
#   PREVIOUS_CHANGE: [v1.4.1 - Add `from __future__ import annotations` to restore Python 3.9 compatibility (PEP 604 `X | None` in make_orchestrator signature).]
# END_CHANGE_SUMMARY
#
"""Unit tests for Orchestrator lifecycle management.

Tests cover:
- Constructor creates 4 UniqueQueues with correct names
- Constructor stores allocation_tracker, active_clouds, allocation_lock
- Start lifecycle creates all 5 background tasks
- Stop lifecycle cancels tasks, calls cleanup on clouds/remote_machines/http
- Cancellation propagation to producer-consumer loops
- Concurrency limits (allocate_limit, deallocate_limit) passed through to _create_producer_consumers
- _clouds_get_capacity inline UoW arithmetic over active_clouds
- _deallocator_consumer calls deallocate_node with uow_factory
- TaskAbandoned event recorded when machine is gone
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.orchestrator import Orchestrator
from yascheduler.application.queue import UniqueQueue
from yascheduler.domain import Engine, EngineRepository, LocalSettings, RemoteDefaults
from yascheduler.domain.events import TaskAbandoned
from yascheduler.domain.model import Task, TaskContext, TaskStatus
from yascheduler.entrypoints import Config
from yascheduler.infra.persistence import PostgresDbConfig

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from yascheduler.application.uow import AbstractUnitOfWork

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
    local = MagicMock(spec=LocalSettings)
    local.conn_machine_pending = 10
    local.allocate_pending = 5
    local.consume_pending = 3
    local.deallocate_pending = 2
    local.webhook_reqs_limit = 5
    local.conn_machine_limit = conn_machine_limit
    local.allocate_limit = allocate_limit
    local.consume_limit = consume_limit
    local.deallocate_limit = deallocate_limit

    remote = MagicMock(spec=RemoteDefaults)
    remote.tasks_dir = PurePosixPath("/tmp/tasks")
    remote.data_dir = PurePosixPath("/tmp/data")
    remote.engines_dir = PurePosixPath("/tmp/engines")
    remote.username = "root"

    config = MagicMock(spec=Config)
    config.local = local
    config.remote = remote
    config.clouds = []
    config.db = MagicMock(spec=PostgresDbConfig)

    return config


def make_orchestrator(
    allocate_limit: int = 3,
    consume_limit: int = 2,
    conn_machine_limit: int = 1,
    deallocate_limit: int = 1,
    sleep_interval: int = 0,
    allocation_tracker: AllocationTracker | None = None,
    active_clouds: list | None = None,
    allocation_lock: asyncio.Lock | None = None,
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
    engine.name = "test_engine"
    engines = MagicMock(spec=EngineRepository)
    engines.values.return_value = [engine]

    log = MagicMock()

    if allocation_tracker is None:
        allocation_tracker = AllocationTracker()
    if active_clouds is None:
        active_clouds = []
    if allocation_lock is None:
        allocation_lock = asyncio.Lock()

    orch = Orchestrator(
        local_settings=config.local,
        remote_defaults=config.remote,
        uow_factory=uow_factory,
        clouds=clouds,
        gateway=gateway,
        engines=engines,
        log=log,
        config_clouds=[],
        local_tasks_dir=Path("/tmp"),
        allocation_tracker=allocation_tracker,
        active_clouds=active_clouds,
        allocation_lock=allocation_lock,
        list_private_keys_fn=lambda _keys_dir: [],
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
        """When a machine is gone for > broken_tasks_passes cycles, TaskAbandoned is recorded and tracker slot released."""
        from yascheduler.application.queue import UMessage

        tracker = MagicMock(spec=AllocationTracker)
        orch = make_orchestrator(allocation_tracker=tracker)

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
        tracker.discard.assert_not_called()

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
        # Tracker slot released on abandon so the int doesn't leak forever.
        tracker.discard.assert_called_once_with(42)


class TestCloudsGetCapacity:
    """_clouds_get_capacity computes capacity over active_clouds and uow.nodes.list_all()."""

    @pytest.mark.asyncio
    async def test_empty_active_clouds_returns_zero(self) -> None:
        """active_clouds=[], nodes=[] → max_nodes=0, current=0 → 0."""
        orch = make_orchestrator(active_clouds=[])
        mock_uow = AsyncMock()
        mock_uow.nodes.list_all = AsyncMock(return_value=[])
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]

        cap = await orch._clouds_get_capacity()
        assert cap == 0

    @pytest.mark.asyncio
    async def test_capacity_with_nodes(self) -> None:
        """active_clouds with max_nodes=10, 2 matching nodes → returns 8."""
        cfg_aws = MagicMock()
        cfg_aws.max_nodes = 10
        cfg_aws.prefix = "aws"
        orch = make_orchestrator(active_clouds=[cfg_aws])

        from yascheduler.domain.model import Node

        nodes = [
            Node(ip="1", ncpus=2, cloud="aws"),
            Node(ip="2", ncpus=2, cloud="aws"),
            Node(ip="3", ncpus=2, cloud="gcp"),
        ]
        mock_uow = AsyncMock()
        mock_uow.nodes.list_all = AsyncMock(return_value=nodes)
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]

        cap = await orch._clouds_get_capacity()
        assert cap == 8  # 10 max - 2 current (aws nodes only)

    @pytest.mark.asyncio
    async def test_capacity_clamped_to_zero(self) -> None:
        """When current exceeds max_nodes, clamp to 0."""
        cfg_aws = MagicMock()
        cfg_aws.max_nodes = 5
        cfg_aws.prefix = "aws"
        orch = make_orchestrator(active_clouds=[cfg_aws])

        from yascheduler.domain.model import Node

        nodes = [Node(ip=str(i), ncpus=2, cloud="aws") for i in range(10)]
        mock_uow = AsyncMock()
        mock_uow.nodes.list_all = AsyncMock(return_value=nodes)
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]

        cap = await orch._clouds_get_capacity()
        assert cap == 0  # max(0, 5-10)

    @pytest.mark.asyncio
    async def test_unrelated_clouds_excluded(self) -> None:
        """Nodes in clouds not in active_clouds don't count toward current."""
        cfg_aws = MagicMock()
        cfg_aws.max_nodes = 8
        cfg_aws.prefix = "aws"
        orch = make_orchestrator(active_clouds=[cfg_aws])

        from yascheduler.domain.model import Node

        nodes = [
            Node(ip="1", ncpus=2, cloud="gcp"),
            Node(ip="2", ncpus=2, cloud="azure"),
            Node(ip="3", ncpus=2, cloud="aws"),
        ]
        mock_uow = AsyncMock()
        mock_uow.nodes.list_all = AsyncMock(return_value=nodes)
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]

        cap = await orch._clouds_get_capacity()
        assert cap == 7  # 8 max - 1 current (only aws counts)


class TestOrchestratorConstructor:
    """Orchestrator constructor stores allocation_tracker, active_clouds, allocation_lock."""

    @pytest.mark.asyncio
    async def test_stores_allocation_tracker(self) -> None:
        """Constructor stores allocation_tracker as self._tracker."""
        tracker = AllocationTracker()
        orch = make_orchestrator(allocation_tracker=tracker)
        assert orch._tracker is tracker

    @pytest.mark.asyncio
    async def test_stores_active_clouds(self) -> None:
        """Constructor stores active_clouds as self._active_clouds."""
        my_list: list = []
        orch = make_orchestrator(active_clouds=my_list)
        assert orch._active_clouds is my_list

    @pytest.mark.asyncio
    async def test_stores_allocation_lock(self) -> None:
        """Constructor stores allocation_lock as self._allocation_lock."""
        my_lock = asyncio.Lock()
        orch = make_orchestrator(allocation_lock=my_lock)
        assert orch._allocation_lock is my_lock

    @pytest.mark.asyncio
    async def test_no_adapters_or_configs_stored(self) -> None:
        """Orchestrator does NOT have _adapters or _configs attributes."""
        orch = make_orchestrator()
        assert not hasattr(orch, "_adapters")
        assert not hasattr(orch, "_configs")


class TestDeallocatorConsumer:
    """_deallocator_consumer calls deallocate_node with uow_factory."""

    @pytest.mark.asyncio
    async def test_calls_deallocate_node_with_uow_factory(self) -> None:
        """deallocate_node called with (node, gateway, clouds, uow_factory)."""
        orch = make_orchestrator()

        mock_uow = AsyncMock()
        node = MagicMock()
        node.ip = "10.0.0.1"
        node.cloud = "aws"
        mock_uow.nodes.get = AsyncMock(return_value=node)
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]

        from yascheduler.application.queue import UMessage

        with patch(
            "yascheduler.application.orchestrator.deallocate_node",
        ) as mock_dealloc:
            msg = UMessage("10.0.0.1", "10.0.0.1")
            await orch._deallocator_consumer(msg)

        mock_dealloc.assert_called_once_with(
            node, orch._gateway, orch._clouds, orch._uow_factory
        )

    @pytest.mark.asyncio
    async def test_disconnects_when_node_not_found(self) -> None:
        """When node is None, gateway.disconnect is called, deallocate_node is NOT called."""
        orch = make_orchestrator()

        mock_uow = AsyncMock()
        mock_uow.nodes.get = AsyncMock(return_value=None)
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]
        orch._gateway.contains = MagicMock(return_value=True)  # type: ignore[method-assign]
        orch._gateway.disconnect = AsyncMock()  # type: ignore[method-assign]

        from yascheduler.application.queue import UMessage

        with patch(
            "yascheduler.application.orchestrator.deallocate_node",
        ) as mock_dealloc:
            msg = UMessage("10.0.0.1", "10.0.0.1")
            await orch._deallocator_consumer(msg)

        orch._gateway.disconnect.assert_called_once_with("10.0.0.1")
        mock_dealloc.assert_not_called()


class TestAllocatorConsumer:
    """_allocator_consumer swallows allocate_task exceptions (worker survival)."""

    @pytest.mark.asyncio
    async def test_swallows_cloud_allocate_error(self) -> None:
        """CloudAllocateError from allocate_task is caught + logged; worker survives."""
        from yascheduler.application.queue import UMessage
        from yascheduler.domain.exceptions import CloudAllocateError

        orch = make_orchestrator()

        task_payload = Task(
            task_id=1,
            label="t",
            context=TaskContext(engine="e"),
            status=TaskStatus.TO_DO,
        )
        msg = UMessage(1, task_payload)

        with patch(
            "yascheduler.application.orchestrator.allocate_task",
            new=AsyncMock(side_effect=CloudAllocateError("VM create failed")),
        ) as mock_alloc:
            # Must not raise — _allocator_consumer swallows to keep worker alive.
            await orch._allocator_consumer(msg)

        mock_alloc.assert_called_once()
        # Error was logged
        orch._log.error.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_swallows_any_exception(self) -> None:
        """Any Exception from allocate_task is caught; worker survives."""
        from yascheduler.application.queue import UMessage

        orch = make_orchestrator()

        task_payload = Task(
            task_id=42,
            label="t",
            context=TaskContext(engine="e"),
            status=TaskStatus.TO_DO,
        )
        msg = UMessage(42, task_payload)

        with patch(
            "yascheduler.application.orchestrator.allocate_task",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ) as mock_alloc:
            await orch._allocator_consumer(msg)

        mock_alloc.assert_called_once()
        orch._log.error.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_propagates_allocate_task_args(self) -> None:
        """_allocator_consumer passes all expected kwargs to allocate_task."""
        from yascheduler.application.queue import UMessage

        orch = make_orchestrator()

        task_payload = Task(
            task_id=7,
            label="t",
            context=TaskContext(engine="e"),
            status=TaskStatus.TO_DO,
        )
        msg = UMessage(7, task_payload)

        with patch(
            "yascheduler.application.orchestrator.allocate_task",
            new=AsyncMock(return_value=False),
        ) as mock_alloc:
            await orch._allocator_consumer(msg)

        mock_alloc.assert_called_once_with(
            task_id=7,
            engines=orch._engines,
            uow_factory=orch._uow_factory,
            gateway=orch._gateway,
            clouds=orch._clouds,
            start_task_on_machine=orch._start_task_on_machine,
            tracker=orch._tracker,
            allocation_lock=orch._allocation_lock,
        )
