"""Daemon orchestrator — manages producer-consumer loops calling use cases."""
# FILE: yascheduler/application/orchestrator.py
# VERSION: 7.13.0
# START_MODULE_CONTRACT
#   PURPOSE: Daemon orchestrator — manages producer-consumer loops calling use cases.
#   SCOPE: Daemon orchestrator: producer-consumer loops driving submit/allocate/consume/deallocate use cases with SSH/cloud collaborators.
#   DEPENDS: M-APPLICATION-UOW, M-DOMAIN-SETTINGS, M-QUEUE, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-APPLICATION-ABANDON-NODE, M-DOMAIN-PORTS, M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE, M-APPLICATION-ALLOCATION-TRACKER, M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY
#   LINKS: M-QUEUE, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-APPLICATION-ABANDON-NODE, M-APPLICATION-UOW, M-DOMAIN-PORTS, M-APPLICATION-ALLOCATION-TRACKER, M-DOMAIN-ENGINE, M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Orchestrator - Daemon loop manager: connect machines, allocate, consume, deallocate, abandon never-connected cloud nodes; in-flight consume guard
#   _asleep_until - Private async sleep-until helper
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v7.13.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v7.12.0 - remove log parameter from __init__/signatures; bind module-local logger = get_logger("M-APPLICATION-ORCHESTRATOR") at module top
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from asyncio.locks import Event
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING

from yascheduler.domain import (
    CloudProvisioner,
    MachineConnectionError,
    MachineRepository,
    MachineSession,
    MachineState,
    Node,
    NodeId,
    Task,
    TaskId,
    TaskStatus,
)

from .abandon_node import abandon_node
from .allocate_task import _count_nodes_by_cloud, allocate_task
from .consume_task import consume_task
from .deallocate_nodes import deallocate_node, deallocate_nodes
from .queue import UMessage, UniqueQueue

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence
    from pathlib import Path, PurePath

    import aiohttp

    from yascheduler.domain import (
        CloudConfig,
        Engine,
        EngineRepository,
        LocalSettings,
        RemoteDefaults,
    )
    from yascheduler.infra import (
        OccupancyChecker,
        OutputDownloader,
        TaskDeployer,
    )

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork


async def _asleep_until(end: datetime) -> None:
    """Sleep until :end:."""
    now = datetime.now(timezone.utc)
    if now >= end:
        return
    await asyncio.sleep((end - now).total_seconds())


# START_CONTRACT: Orchestrator
#   PURPOSE: Manage the daemon's 4 producer-consumer loops, delegating business logic to use cases.
#   INPUTS: { local_settings, remote_defaults, uow_factory, clouds, gateway, task_deployer, output_downloader, occupancy_checker, engines, config_clouds, local_tasks_dir, allocation_tracker, active_clouds, allocation_lock }
#   OUTPUTS: { Orchestrator instance }
#   SIDE_EFFECTS: Creates queues, cancellation event.
#   LINKS: M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-APPLICATION-UOW, M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY
# END_CONTRACT: Orchestrator
class Orchestrator:
    """Manage the daemon's 4 producer-consumer loops, delegating business logic to use cases."""

    # START_CONTRACT: Orchestrator.__init__
    #   PURPOSE: Initialise orchestrator with all daemon dependencies.
    #   INPUTS: { local_settings, remote_defaults, uow_factory, clouds, repository, task_deployer, output_downloader, occupancy_checker, engines, config_clouds, local_tasks_dir, allocation_tracker, active_clouds, allocation_lock, list_private_keys_fn, http_session }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates UniqueQueues.
    #   LINKS: M-APPLICATION-UOW, M-QUEUE, M-SSH-REPOSITORY, M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY, M-SSH-KEYS
    # END_CONTRACT: Orchestrator.__init__
    def __init__(
        self,
        local_settings: LocalSettings,
        remote_defaults: RemoteDefaults,
        uow_factory: Callable[[], AbstractUnitOfWork],
        clouds: CloudProvisioner,
        repository: MachineRepository,
        task_deployer: TaskDeployer,
        output_downloader: OutputDownloader,
        occupancy_checker: OccupancyChecker,
        engines: EngineRepository,
        config_clouds: Sequence[CloudConfig],
        local_tasks_dir: Path,
        allocation_tracker: AllocationTracker,
        active_clouds: Sequence[CloudConfig],
        allocation_lock: asyncio.Lock,
        list_private_keys_fn: Callable[[Path], Sequence[PurePath]],
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialise orchestrator with all daemon dependencies."""
        self._local_settings = local_settings
        self._remote_defaults = remote_defaults
        self._uow_factory = uow_factory
        self._clouds = clouds
        self._repository = repository
        self._task_deployer = task_deployer
        self._output_downloader = output_downloader
        self._occupancy_checker = occupancy_checker
        self._engines = engines
        self._config_clouds = config_clouds
        self._local_tasks_dir = local_tasks_dir
        self._http_session = http_session
        self._tracker = allocation_tracker
        self._active_clouds = active_clouds
        self._allocation_lock = allocation_lock
        self._list_private_keys_fn = list_private_keys_fn

        self._bg_jobs: set[asyncio.Task[None]] = set()
        self._cancellation_event = Event()
        self._machine_connected_event = Event()
        self._sleep_interval: int = min(e.sleep_interval for e in engines.values())
        self._occupancy_started: set[NodeId] = set()
        # In-flight consume task ids — prevents two workers from concurrently
        # consuming the same RUNNING task across overlapping producer cycles.
        # Same-event-loop check/add/remove are atomic (no await between check
        # and add). In-memory only; daemon restart resets the guard.
        self._consuming: set[TaskId] = set()
        # Per-node first-seen monotonic timestamp of a consecutive connect
        # failure (keyed by NodeId); in-memory only (daemon restart resets
        # grace windows).
        self._connect_failures: dict[NodeId, float] = {}
        # Single-execution guard for stop(): set synchronously at the top of
        # stop() with no `await` between check and set — atomic in
        # single-threaded asyncio. In-memory only; a fresh Orchestrator
        # starts with _stopped = False.
        self._stopped: bool = False

        lcfg = local_settings
        self._conn_machine_q: UniqueQueue[NodeId, Node] = UniqueQueue(
            "conn_machine",
            maxsize=lcfg.conn_machine_pending,
        )
        self._allocate_q: UniqueQueue[TaskId, Task] = UniqueQueue(
            "allocate",
            maxsize=lcfg.allocate_pending,
        )
        self._consume_q: UniqueQueue[TaskId, Task] = UniqueQueue(
            "consume",
            maxsize=lcfg.consume_pending,
        )
        self._deallocate_q: UniqueQueue[NodeId, Node] = UniqueQueue(
            "deallocate",
            maxsize=lcfg.deallocate_pending,
        )

    # ---- Task deployment wrapper ----

    # START_CONTRACT: Orchestrator._start_task_on_machine
    #   PURPOSE: Thin wrapper — resolve ncpus via UoW, delegate to task_deployer.start_task_on_machine.
    #   INPUTS: { session: MachineSession, engine: Engine, task: Task }
    #   OUTPUTS: { bool - True on successful spawn }
    #   SIDE_EFFECTS: Reads node from DB, calls task_deployer.start_task_on_machine.
    #   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS, M-SSH-OPS-DEPLOY, M-SSH-SESSION
    # END_CONTRACT: Orchestrator._start_task_on_machine
    async def _start_task_on_machine(
        self,
        session: MachineSession,
        engine: Engine,
        task: Task,
    ) -> bool:
        # START_BLOCK_RESOLVE_NCPUS
        async with self._uow_factory() as uow:
            node = (
                await uow.nodes.get_by_id(task.allocated_node_id)
                if task.allocated_node_id is not None
                else None
            )
        ncpus = (
            node.ncpus
            if node is not None and node.ncpus is not None
            else await session.get_cpu_cores()
        )
        # END_BLOCK_RESOLVE_NCPUS
        return await self._task_deployer.start_task_on_machine(
            session,
            engine,
            task,
            ncpus,
            self._remote_defaults.engines_dir,
        )

    # ---- Stats ----

    # START_CONTRACT: Orchestrator._print_stats
    #   PURPOSE: Periodically log queue sizes, node counts, and task counts.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Logs statistics periodically.
    #   LINKS: M-APPLICATION-UOW
    # END_CONTRACT: Orchestrator._print_stats
    async def _print_stats(self) -> None:
        while not self._cancellation_event.is_set():
            end_time = datetime.now(timezone.utc) + timedelta(seconds=10)
            # START_BLOCK_STATS_RESILIENCE
            try:
                async with self._uow_factory() as uow:
                    ncounters = await uow.nodes.count_by_status()
                    tcounters = await uow.tasks.count_by_status()
                n_busy = sum(
                    1
                    for s in self._repository.list_connected()
                    if s.machine.state == MachineState.BUSY
                )
                tmpl = (
                    "THREADS: {tasks} "
                    "NODES: busy:{n_busy}/enabled:{n_enabled}/total:{n_total} "
                    "TASKS: run:{t_run}/todo:{t_todo}/done:{t_done}"
                )
                msg = tmpl.format(
                    tasks=len(asyncio.all_tasks()),
                    n_busy=n_busy,
                    n_enabled=ncounters.get(True, 0),
                    n_total=sum(ncounters.values()),
                    t_run=tcounters.get(TaskStatus.RUNNING, 0),
                    t_todo=tcounters.get(TaskStatus.TO_DO, 0),
                    t_done=tcounters.get(TaskStatus.DONE, 0),
                )
                logger.info(msg)

                queues = [
                    self._conn_machine_q,
                    self._allocate_q,
                    self._deallocate_q,
                    self._consume_q,
                ]
                qmsgs = [f"{q.name}: {q.psize()}/{q.qsize()}" for q in queues]
                logger.info("QUEUES: %s", " ".join(qmsgs))
            # CancelledError is a BaseException — do NOT broaden to
            # `except BaseException` or shutdown will be swallowed.
            except Exception as err:
                logger.debug("ERROR", extra={"context": "stats", "err": err})
                logger.exception("stats print failed")
            finally:
                await _asleep_until(end_time)
            # END_BLOCK_STATS_RESILIENCE

    # ---- Producers / Consumers ----

    async def _connect_machine_producer(
        self,
    ) -> AsyncGenerator[UMessage[NodeId, Node], None]:
        async with self._uow_factory() as uow:
            enabled_nodes = await uow.nodes.list_enabled()
        # START_BLOCK_FILTER_NOT_CONNECTED
        # Yield every enabled node not currently registered in the gateway,
        # regardless of cloud. Static (cloud is None) and cloud-provisioned
        # nodes are both connected here; the never-abandon guarantee for
        # static nodes is enforced in _connect_machine_consumer before the
        # grace-check (see START_BLOCK_STATIC_NODE_RETRY).
        new_nodes = [
            n for n in enabled_nodes if not self._repository.contains(n.node_id)
        ]
        # END_BLOCK_FILTER_NOT_CONNECTED
        for node in new_nodes:
            yield UMessage(node.node_id, node)

    async def _connect_machine_consumer(self, msg: UMessage[NodeId, Node]) -> None:
        node = msg.payload
        keys = await asyncio.get_running_loop().run_in_executor(
            None,
            self._list_private_keys_fn,
            self._local_settings.keys_dir,
        )
        try:
            await self._repository.connect(
                node=node,
                client_keys=keys,
                connect_timeout=10,
                data_dir=self._remote_defaults.data_dir,
                engines_dir=self._remote_defaults.engines_dir,
                tasks_dir=self._remote_defaults.tasks_dir,
            )
            # START_BLOCK_CONNECT_RESET_FAILURE_TIMER
            self._connect_failures.pop(node.node_id, None)
            # END_BLOCK_CONNECT_RESET_FAILURE_TIMER
            self._machine_connected_event.set()
        except MachineConnectionError as err:
            # START_BLOCK_STATIC_NODE_RETRY
            # Static operator-managed nodes (cloud is None) are retried
            # indefinitely on every producer cycle and never enter the
            # abandon path. The guard sits before the grace-check so
            # _connect_failures is never populated and _connect_grace_for
            # is never called on the production path for static nodes.
            if node.cloud is None:
                logger.debug(
                    "CONNECT_RETRY_STATIC",
                    extra={
                        "node_id": node.node_id,
                        "hostname": node.hostname,
                        "err": err,
                    },
                )
                logger.warning("static node %s connect failed: %s", node.hostname, err)
                return
            # END_BLOCK_STATIC_NODE_RETRY
            # START_BLOCK_CONNECT_GRACE_CHECK
            first_seen = self._connect_failures.setdefault(
                node.node_id,
                time.monotonic(),
            )
            age = time.monotonic() - first_seen
            grace = self._connect_grace_for(node.cloud)
            if age < grace:
                logger.debug(
                    "CONNECT_RETRY",
                    extra={
                        "node_id": node.node_id,
                        "hostname": node.hostname,
                        "age": age,
                        "grace": grace,
                        "err": err,
                    },
                )
                logger.warning("cloud node %s connect failed: %s", node.hostname, err)
                return
            # END_BLOCK_CONNECT_GRACE_CHECK

            # START_BLOCK_CONNECT_ABANDON
            logger.debug(
                "CONNECT_ABANDON",
                extra={
                    "node_id": node.node_id,
                    "hostname": node.hostname,
                    "age": age,
                    "grace": grace,
                },
            )
            logger.exception(
                "abandoning cloud node %s after grace exceeded",
                node.hostname,
            )
            try:
                await abandon_node(
                    node,
                    self._clouds,
                    self._uow_factory,
                    self._tracker,
                )
            except Exception as abandon_err:
                logger.debug(
                    "ABANDON_FAILED",
                    extra={
                        "node_id": node.node_id,
                        "hostname": node.hostname,
                        "err": abandon_err,
                    },
                )
                logger.exception(
                    "abandon_node failed for node %s",
                    node.hostname,
                )
            self._connect_failures.pop(node.node_id, None)
            # END_BLOCK_CONNECT_ABANDON
        except Exception:
            logger.exception("An error occuried on remote machine creation")

    def _connect_grace_for(self, cloud: str | None) -> int:
        if cloud is None:
            return 120
        for cfg in self._config_clouds:
            if cfg.prefix == cloud:
                return cfg.connect_grace
        return 120

    async def _allocator_producer(
        self,
    ) -> AsyncGenerator[UMessage[TaskId, Task], None]:
        ccap = await self._clouds_get_capacity()
        tlim = max(ccap, len(self._repository.list_free(None)), 10)
        async with self._uow_factory() as uow:
            tasks = await uow.tasks.list_by_status({TaskStatus.TO_DO}, limit=tlim)
        if tasks:
            ids = [str(t.task_id) for t in tasks]
            logger.debug("ALLOCATOR_PRODUCER", extra={"task_ids": ", ".join(ids)})
        for task in tasks:
            yield UMessage(task.task_id, task)

    # START_CONTRACT: Orchestrator._allocator_consumer
    #   PURPOSE: Run allocate_task for one queued task; swallow exceptions to keep the worker alive.
    #   INPUTS: { msg: UMessage[TaskId, Task] }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Delegates all allocation side effects to allocate_task; logs and swallows any exception so the allocator worker is not killed (mirrors _deallocator_consumer).
    #   LINKS: M-APPLICATION-ALLOCATE
    # END_CONTRACT: Orchestrator._allocator_consumer
    async def _allocator_consumer(self, msg: UMessage[TaskId, Task]) -> None:
        # START_BLOCK_ALLOCATE
        logger.debug("ALLOCATE", extra={"task_id": msg.id})
        try:
            await allocate_task(
                task_id=msg.id,
                engines=self._engines,
                uow_factory=self._uow_factory,
                repository=self._repository,
                occupancy_checker=self._occupancy_checker,
                clouds=self._clouds,
                start_task_on_machine=self._start_task_on_machine,
                tracker=self._tracker,
                allocation_lock=self._allocation_lock,
                remote_tasks_dir=self._remote_defaults.tasks_dir,
            )
        except Exception:
            logger.exception("Allocator error for task %s", msg.id)
        # END_BLOCK_ALLOCATE

    async def _task_consumer_producer(
        self,
    ) -> AsyncGenerator[UMessage[TaskId, Task], None]:
        async with self._uow_factory() as uow:
            tasks = await uow.tasks.list_by_status({TaskStatus.RUNNING})
        # START_BLOCK_SKIP_IN_FLIGHT
        # Skip tasks currently being consumed by another worker to prevent
        # two workers from concurrently consuming the same RUNNING task across
        # overlapping producer cycles (same event loop → atomic check).
        for task in tasks:
            if task.task_id in self._consuming:
                continue
            yield UMessage(task.task_id, task)
        # END_BLOCK_SKIP_IN_FLIGHT

    # START_CONTRACT: Orchestrator._task_consumer_consumer
    #   PURPOSE: Check task machine state, record TaskAbandoned for lost nodes, or consume completed tasks.
    #   INPUTS: { msg: UMessage[TaskId, Task], machine_not_found: Counter[TaskId] }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Records TaskAbandoned event for lost nodes; calls consume_task use case for free machines;
    #     guards the task id in self._consuming around the await; discards node_id from _occupancy_started only when
    #     consume_task returns True (finalised) — deferred (False) keeps the node_id registered for retry.
    #   LINKS: M-APPLICATION-CONSUME, M-DOMAIN-EVENTS
    # END_CONTRACT: Orchestrator._task_consumer_consumer
    async def _task_consumer_consumer(
        self,
        msg: UMessage[TaskId, Task],
        machine_not_found: Counter,
    ) -> None:
        broken_tasks_passes = 20
        task_id, task = msg.id, msg.payload
        node_id = task.allocated_node_id
        session = self._repository.get_session(node_id) if node_id is not None else None
        if session is None:
            # START_BLOCK_MACHINE_GONE
            logger.warning("machine gone for task_id=%s node_id=%s", task_id, node_id)
            machine_not_found.update([task_id])
            if machine_not_found[task_id] > broken_tasks_passes:
                # Single atomic transition: RUNNING→DONE with error; emits
                # TaskAbandoned only when node_id is not None.
                task = task.abandon(node_id)
                # START_BLOCK_ABANDON_PERSIST
                # Persist the TaskAbandoned transition. The row may have been
                # concurrently deleted between the producer's list_by_status
                # read and this save — in that case save() raises
                # TaskRowNotFoundError, which propagates to the consumer-worker
                # `except Exception` wrap and is logged. The tracker slot is
                # discarded in a finally so a 0-row raise cannot leak an
                # in-flight allocation slot for the daemon's lifetime.
                try:
                    async with self._uow_factory() as uow:
                        await uow.tasks.save(task)
                        await uow.commit()
                finally:
                    # Drop the in-flight allocation slot so the abandoned
                    # task_id can't falsely dedup a future task if task IDs
                    # ever recycle. Runs even if save() raised.
                    self._tracker.discard(task_id)
                # END_BLOCK_ABANDON_PERSIST
            # END_BLOCK_MACHINE_GONE
            return

        machine = session.machine

        # session.machine.node_id is the authoritative non-optional NodeId key
        # (matches task.allocated_node_id for a correctly-bound RUNNING task).
        key = machine.node_id
        if key not in self._occupancy_started:
            engine = self._engines.get(task.engine)
            if engine:
                self._occupancy_checker.start_occupancy_check(session, engine)
                self._occupancy_started.add(key)
                session = self._repository.get_session(key)
                if session is None:
                    return
                machine = session.machine

        # START_BLOCK_CONSUME
        if machine.state == MachineState.FREE and key in self._occupancy_started:
            logger.debug("CONSUME", extra={"node_id": key, "task_id": task_id})
            # Guard the task id so the next producer cycle does not re-yield it
            # to another worker while this consume is in flight.
            self._consuming.add(task_id)
            try:
                finalised = await consume_task(
                    task_id=task_id,
                    session=session,
                    output_downloader=self._output_downloader,
                    engines=self._engines,
                    uow_factory=self._uow_factory,
                    local_tasks_dir=self._local_tasks_dir,
                    tracker=self._tracker,
                )
            finally:
                self._consuming.discard(task_id)
            # Discard the node_id from _occupancy_started only when finalised
            # so a deferred (transient-only) task is re-consumed on the next
            # cycle.
            if finalised:
                self._occupancy_started.discard(key)
        # END_BLOCK_CONSUME

    # ---- Deallocator producer-consumer ----

    # START_CONTRACT: Orchestrator._deallocator_producer
    #   PURPOSE: Find idle nodes exceeding tolerance, disable them via use case, yield disabled Node objects for deallocation.
    #   INPUTS: { None }
    #   OUTPUTS: { AsyncGenerator[UMessage[NodeId, Node], None] - yields disabled cloud Node objects (id == node.node_id) }
    #   SIDE_EFFECTS: Disables idle nodes in DB via deallocate_nodes use case.
    #   LINKS: M-APPLICATION-DEALLOCATE
    # END_CONTRACT: Orchestrator._deallocator_producer
    async def _deallocator_producer(
        self,
    ) -> AsyncGenerator[UMessage[NodeId, Node], None]:
        # START_BLOCK_COLLECT_IDLE
        # free_since is monotonic; pass it through unchanged so deallocate_nodes
        # compares against time.monotonic() and stays immune to wall-clock jumps.
        # Keyed by NodeId (was ip) — dup-IP nodes have distinct node_id keys.
        idle_machines: dict[NodeId, float] = {}
        for s in self._repository.list_connected():
            if (
                s.machine.state == MachineState.FREE
                and s.machine.free_since is not None
            ):
                idle_machines[s.machine.node_id] = s.machine.free_since
        # END_BLOCK_COLLECT_IDLE

        # START_BLOCK_DEALLOCATE_USE_CASE
        disabled_nodes = await deallocate_nodes(
            self._uow_factory,
            self._config_clouds,
            idle_machines,
        )
        # END_BLOCK_DEALLOCATE_USE_CASE

        # START_BLOCK_YIELD_DISABLED
        for node in disabled_nodes:
            yield UMessage(node.node_id, node)
        # END_BLOCK_YIELD_DISABLED

    # START_CONTRACT: Orchestrator._deallocator_consumer
    #   PURPOSE: Cloud-deallocate a single disabled node via deallocate_node.
    #   INPUTS: { msg: UMessage[NodeId, Node] - disabled node (payload is the Node object) }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Delegates SSH disconnect + disable + cloud delete + remove to deallocate_node (which owns SSH teardown internally); logs and swallows any Exception so the worker survives.
    #   LINKS: M-APPLICATION-DEALLOCATE
    # END_CONTRACT: Orchestrator._deallocator_consumer
    async def _deallocator_consumer(self, msg: UMessage[NodeId, Node]) -> None:
        node = msg.payload
        try:
            await deallocate_node(
                node,
                self._repository,
                self._clouds,
                self._uow_factory,
            )
        except Exception:
            logger.exception(
                "Deallocator error for node_id=%s hostname=%s",
                node.node_id,
                node.hostname,
            )

    # ---- Infrastructure ----

    # START_CONTRACT: Orchestrator._clouds_get_capacity
    #   PURPOSE: Compute available cloud capacity as max(0, total_max_nodes - current_count) over active clouds.
    #   INPUTS: { None - reads self._uow_factory and self._active_clouds }
    #   OUTPUTS: { int - available node slots across all active clouds }
    #   SIDE_EFFECTS: None — read-only.
    #   LINKS: M-APPLICATION-UOW, M-DOMAIN-SETTINGS, M-DOMAIN-MODEL
    # END_CONTRACT: Orchestrator._clouds_get_capacity
    async def _clouds_get_capacity(self) -> int:
        # START_BLOCK_READ_COUNTS
        async with self._uow_factory() as uow:
            nodes = await uow.nodes.list_all()
        counts = _count_nodes_by_cloud(nodes)
        # END_BLOCK_READ_COUNTS

        # START_BLOCK_COMPUTE_CAPACITY
        max_nodes = sum(c.max_nodes for c in self._active_clouds)
        current = sum(counts.get(c.prefix, 0) for c in self._active_clouds)
        diff = max_nodes - current
        return max(0, diff)
        # END_BLOCK_COMPUTE_CAPACITY

    # START_CONTRACT: Orchestrator._create_producer_consumers
    #   PURPOSE: Run a resilient producer-consumer loop with N workers; self-heal on transient producer and consumer errors.
    #   INPUTS: { queue: UniqueQueue, producer: Callable, consumer: Callable, workers_num: int = 1 }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Spawns worker tasks registered in BOTH the local workers set and self._bg_jobs (so
    #     stop()'s cancel cascade reaches them even on a BaseException exit); drives the producer each
    #     _sleep_interval tick; on a transient producer Exception logs and continues on the next tick;
    #     on a transient consumer Exception inside worker() logs and continues processing subsequent
    #     messages (the worker task is NOT killed); on CancelledError drains the queue (queue.join),
    #     cancels workers, and awaits them. CancelledError (a BaseException since Python 3.8) propagates
    #     past `except Exception` to the graceful-drain `except CancelledError` — neither the producer-error
    #     nor the consumer-error handler SHALL run on graceful shutdown.
    #   LINKS: M-QUEUE
    # END_CONTRACT: Orchestrator._create_producer_consumers
    async def _create_producer_consumers(
        self,
        queue: UniqueQueue,
        producer: Callable,
        consumer: Callable,
        workers_num: int = 1,
    ) -> None:
        async def worker() -> None:
            while not self._cancellation_event.is_set():
                msg = await queue.get()
                # START_BLOCK_CONSUMER_RESILIENCE
                # Mirror the producer-error wrap: a raise out of consumer(msg)
                # would otherwise kill the worker task silently. Catch Exception
                # (not BaseException) so CancelledError still propagates to the
                # graceful-drain path. The finally keeps the queue item dequeued.
                try:
                    await consumer(msg)
                except Exception as err:
                    logger.debug(
                        "CONSUMER_ERROR",
                        extra={"queue": queue.name, "err": err},
                    )
                    logger.exception("consumer error on queue %s", queue.name)
                finally:
                    queue.item_done(msg)
                # END_BLOCK_CONSUMER_RESILIENCE

        workers: set[asyncio.Task] = set()
        # START_BLOCK_REGISTER_WORKERS
        # Workers are background jobs for the daemon's lifetime — register them
        # in self._bg_jobs so stop()'s cancel cascade reaches them even if the
        # parent exits via a BaseException (SystemExit/KeyboardInterrupt) that
        # `except Exception` does not catch. The local `workers` set is kept
        # for the `except CancelledError` drain path; double-cancel is idempotent.
        for _ in range(workers_num):
            t = asyncio.create_task(worker())
            workers.add(t)
            self._bg_jobs.add(t)
        # END_BLOCK_REGISTER_WORKERS

        try:
            while not self._cancellation_event.is_set():
                end_time = datetime.now(timezone.utc) + timedelta(
                    seconds=self._sleep_interval,
                )
                # START_BLOCK_PRODUCER_RESILIENCE
                try:
                    async for msg in producer():
                        await queue.put(msg)
                # CancelledError is a BaseException (not Exception) since Python
                # 3.8 — do NOT broaden this to `except BaseException` or graceful
                # shutdown will be swallowed and the drain below bypassed.
                except Exception as err:
                    logger.debug(
                        "PRODUCER_ERROR",
                        extra={"queue": queue.name, "err": err},
                    )
                    logger.exception("producer error on queue %s", queue.name)
                finally:
                    await _asleep_until(end_time)
                # END_BLOCK_PRODUCER_RESILIENCE
        except asyncio.CancelledError:
            if not queue.empty():
                logger.info(
                    "Queue %s has %s items - waiting",
                    queue.name,
                    queue.qsize(),
                )
                await queue.join()
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    # ---- Lifecycle ----

    # START_CONTRACT: Orchestrator._await_first_machine
    #   PURPOSE: Wait up to 30 seconds for at least one machine to connect.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None
    #   LINKS: M-SSH-REPOSITORY
    # END_CONTRACT: Orchestrator._await_first_machine
    async def _await_first_machine(self) -> None:
        # START_BLOCK_WAIT_MACHINES
        if len(self._repository) > 0:
            return

        async def _wait() -> None:
            await self._machine_connected_event.wait()

        wait_task = asyncio.create_task(_wait())
        timeout_task = asyncio.create_task(asyncio.sleep(30))
        _done, pending = await asyncio.wait(
            [wait_task, timeout_task],
            return_when="FIRST_COMPLETED",
        )
        for t in pending:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        # END_BLOCK_WAIT_MACHINES

    async def _shutdown_barrier(self) -> None:
        await asyncio.gather(*self._bg_jobs, return_exceptions=True)

    # START_CONTRACT: Orchestrator.start
    #   PURPOSE: Start all producer-consumer loops for the daemon.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Starts background tasks, connects machines, runs producer-consumer loops with config-limited concurrency.
    #   LINKS: M-QUEUE, M-APPLICATION-UOW
    # END_CONTRACT: Orchestrator.start
    async def start(self) -> None:
        """Start all producer-consumer loops for the daemon."""
        logger.debug(
            "START",
            extra={"engines": ", ".join(e.name for e in self._engines.values())},
        )

        self._bg_jobs.add(asyncio.create_task(self._print_stats()))

        conn_machine_co = self._create_producer_consumers(
            queue=self._conn_machine_q,
            producer=self._connect_machine_producer,
            consumer=self._connect_machine_consumer,
            workers_num=self._local_settings.conn_machine_limit,
        )
        self._bg_jobs.add(asyncio.create_task(conn_machine_co))

        await self._await_first_machine()

        allocate_co = self._create_producer_consumers(
            queue=self._allocate_q,
            producer=self._allocator_producer,
            consumer=self._allocator_consumer,
            workers_num=self._local_settings.allocate_limit,
        )
        self._bg_jobs.add(asyncio.create_task(allocate_co))

        machine_not_found: Counter[TaskId] = Counter()
        consume_co = self._create_producer_consumers(
            queue=self._consume_q,
            producer=self._task_consumer_producer,
            consumer=partial(
                self._task_consumer_consumer,
                machine_not_found=machine_not_found,
            ),
            workers_num=self._local_settings.consume_limit,
        )
        self._bg_jobs.add(asyncio.create_task(consume_co))

        deallocate_co = self._create_producer_consumers(
            queue=self._deallocate_q,
            producer=self._deallocator_producer,
            consumer=self._deallocator_consumer,
            workers_num=self._local_settings.deallocate_limit,
        )
        self._bg_jobs.add(asyncio.create_task(deallocate_co))

        await self._shutdown_barrier()

    # START_CONTRACT: Orchestrator.stop
    #   PURPOSE: Signal the daemon to stop and clean up non-session resources.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Cancels bg jobs, disconnects machines, stops clouds, closes http_session; idempotent via _stopped guard; per-step isolation.
    #   LINKS: M-CLOUD-PROVISIONER, M-SSH-REPOSITORY
    # END_CONTRACT: Orchestrator.stop
    async def stop(self) -> None:
        """Signal the daemon to stop and clean up non-session resources."""
        # START_BLOCK_STOP_GUARD
        if self._stopped:
            return
        self._stopped = True
        # END_BLOCK_STOP_GUARD
        logger.info("Stopping...")
        self._cancellation_event.set()

        # START_BLOCK_STOP_AWAIT_JOBS
        for task in self._bg_jobs:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # CancelledError is BaseException (not Exception) since Py3.8, so
            # the two except clauses are distinct and non-overlapping. Catches
            # a bg job that already died with a non-CancelledError before
            # shutdown so the pre-existing exception does not abort cleanup.
            except Exception as e:
                logger.debug("BG_JOB_ENDED", extra={"err": e})
        # END_BLOCK_STOP_AWAIT_JOBS

        # START_BLOCK_STOP_CLOUDS
        try:
            await self._clouds.stop()
        except Exception as e:
            logger.warning("clouds stop failed: %s", e)
        # END_BLOCK_STOP_CLOUDS

        # START_BLOCK_STOP_GATEWAY
        try:
            await self._repository.disconnect_all()
        except Exception as e:
            logger.warning("disconnect all failed: %s", e)
        # END_BLOCK_STOP_GATEWAY

        # START_BLOCK_STOP_HTTP
        if self._http_session is not None:
            try:
                await self._http_session.close()
            except Exception as e:
                logger.warning("http close failed: %s", e)
        self._http_session = None
        # END_BLOCK_STOP_HTTP
