# FILE: yascheduler/application/orchestrator.py
# VERSION: 5.4.0
# START_MODULE_CONTRACT
#   PURPOSE: Daemon orchestrator — manages producer-consumer loops calling use cases.
#   SCOPE: Orchestrator class with start/stop lifecycle, 4 loop pairs, stats, and SSH helpers.
#   DEPENDS: M-APPLICATION-UOW, M-CONFIG, M-QUEUE, M-SHARED, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-DOMAIN-PORTS, M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-CONFIG, M-QUEUE, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-APPLICATION-UOW, M-DOMAIN-PORTS, M-APPLICATION-ALLOCATION-TRACKER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Orchestrator - Daemon loop manager: connect machines, allocate, consume, deallocate
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v5.4.0 - Add START_CONTRACT on _clouds_get_capacity (GRACE audit fix).
#   PREVIOUS_CHANGE: v5.3.0 - Pass free_since (monotonic) straight through to deallocate_nodes; remove wall-clock conversion that could skew idle detection under DST/NTP jumps (review-hardening).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging  # noqa: TC003 — used at runtime for log calls
from asyncio.locks import Event
from collections import Counter
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from yascheduler.domain import (
    CloudProvisioner,
    ConnectedMachine,
    MachineConnectionError,
    MachineGateway,
    MachineState,
    Node,
    Task,
    TaskAbandoned,
    TaskExecutionEngine,
    TaskStatus,
)
from yascheduler.shared import asleep_until

from .allocate_task import _count_nodes_by_cloud, allocate_task
from .consume_task import consume_task
from .deallocate_nodes import deallocate_node, deallocate_nodes
from .queue import UMessage, UniqueQueue

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence
    from pathlib import Path

    import aiohttp

    from yascheduler.config import Config, ConfigCloud, EngineRepository

    from .allocation_tracker import AllocationTracker
    from .uow import AbstractUnitOfWork


# START_CONTRACT: Orchestrator
#   PURPOSE: Manage the daemon's 4 producer-consumer loops, delegating business logic to use cases.
#   INPUTS: { config, uow_factory, clouds, gateway, engines, log, config_clouds, local_tasks_dir, allocation_tracker, active_clouds, allocation_lock }
#   OUTPUTS: { Orchestrator instance }
#   SIDE_EFFECTS: Creates queues, cancellation event.
#   LINKS: M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-APPLICATION-UOW
# END_CONTRACT: Orchestrator
class Orchestrator:
    # START_CONTRACT: Orchestrator.__init__
    #   PURPOSE: Initialise orchestrator with all daemon dependencies.
    #   INPUTS: { config: Config, uow_factory: Callable[[], AbstractUnitOfWork], clouds: CloudProvisioner, gateway: MachineGateway, engines: EngineRepository, log: Logger, config_clouds: Sequence[ConfigCloud], local_tasks_dir: Path, allocation_tracker: AllocationTracker, active_clouds: Sequence[ConfigCloud], allocation_lock: asyncio.Lock }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates UniqueQueues.
    #   LINKS: M-CONFIG, M-APPLICATION-UOW, M-QUEUE, M-SSH-GATEWAY
    # END_CONTRACT: Orchestrator.__init__
    def __init__(
        self,
        config: Config,
        uow_factory: Callable[[], AbstractUnitOfWork],
        clouds: CloudProvisioner,
        gateway: MachineGateway,
        engines: EngineRepository,
        log: logging.Logger,
        config_clouds: Sequence[ConfigCloud],
        local_tasks_dir: Path,
        allocation_tracker: AllocationTracker,
        active_clouds: Sequence[ConfigCloud],
        allocation_lock: asyncio.Lock,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._config = config
        self._uow_factory = uow_factory
        self._clouds = clouds
        self._gateway = gateway
        self._engines = engines
        self._log = log
        self._config_clouds = config_clouds
        self._local_tasks_dir = local_tasks_dir
        self._http_session = http_session
        self._tracker = allocation_tracker
        self._active_clouds = active_clouds
        self._allocation_lock = allocation_lock

        self._bg_jobs: set[asyncio.Task[None]] = set()
        self._cancellation_event = Event()
        self._machine_connected_event = Event()
        self._sleep_interval: int = min(e.sleep_interval for e in engines.values())
        self._occupancy_started: set[str] = set()

        lcfg = config.local
        self._conn_machine_q: UniqueQueue[str, Node] = UniqueQueue(
            "conn_machine", maxsize=lcfg.conn_machine_pending
        )
        self._allocate_q: UniqueQueue[int, Task] = UniqueQueue(
            "allocate", maxsize=lcfg.allocate_pending
        )
        self._consume_q: UniqueQueue[int, Task] = UniqueQueue(
            "consume", maxsize=lcfg.consume_pending
        )
        self._deallocate_q: UniqueQueue[str, str] = UniqueQueue(
            "deallocate", maxsize=lcfg.deallocate_pending
        )

    # ---- Task deployment wrapper ----

    # START_CONTRACT: Orchestrator._start_task_on_machine
    #   PURPOSE: Thin wrapper — resolve ncpus via UoW, delegate to gateway.start_task_on_machine.
    #   INPUTS: { machine: ConnectedMachine, engine: TaskExecutionEngine, task: Task }
    #   OUTPUTS: { bool - True on successful spawn }
    #   SIDE_EFFECTS: Reads node from DB, calls gateway.start_task_on_machine.
    #   LINKS: M-APPLICATION-UOW, M-DOMAIN-PORTS
    # END_CONTRACT: Orchestrator._start_task_on_machine
    async def _start_task_on_machine(
        self,
        machine: ConnectedMachine,
        engine: TaskExecutionEngine,
        task: Task,
    ) -> bool:
        # START_BLOCK_RESOLVE_NCPUS
        async with self._uow_factory() as uow:
            node = await uow.nodes.get(task.allocated_ip or "")
        ncpus = (node and node.ncpus) or await self._gateway.get_cpu_cores(machine.ip)
        # END_BLOCK_RESOLVE_NCPUS
        return await self._gateway.start_task_on_machine(
            machine, engine, task, ncpus, self._config.remote.engines_dir
        )

    # ---- Stats ----

    # START_CONTRACT: Orchestrator._print_stats
    #   PURPOSE: Periodically log queue sizes, node counts, and task counts.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Logs statistics every 10 seconds.
    #   LINKS: M-APPLICATION-UOW
    # END_CONTRACT: Orchestrator._print_stats
    async def _print_stats(self) -> None:
        while not self._cancellation_event.is_set():
            end_time = datetime.now() + timedelta(seconds=10)
            async with self._uow_factory() as uow:
                ncounters = await uow.nodes.count_by_status()
                tcounters = await uow.tasks.count_by_status()
            n_busy = sum(
                1
                for m in self._gateway.list_connected()
                if m.state == MachineState.BUSY
            )
            tmpl = (
                "THREADS: {tasks} "
                "NODES: busy:{n_busy}/enabled:{n_enabled}/total:{n_total} "
                "TASKS: run:{t_run}/todo:{t_todo}/done:{t_done}"
            )
            msg = tmpl.format(
                tasks=len(asyncio.all_tasks()),
                n_busy=n_busy,
                n_enabled=ncounters[True],
                n_total=sum(ncounters.values()),
                t_run=tcounters.get(TaskStatus.RUNNING, 0),
                t_todo=tcounters.get(TaskStatus.TO_DO, 0),
                t_done=tcounters.get(TaskStatus.DONE, 0),
            )
            self._log.info(msg)

            queues = [
                self._conn_machine_q,
                self._allocate_q,
                self._deallocate_q,
                self._consume_q,
            ]
            qmsgs = [f"{q.name}: {q.psize()}/{q.qsize()}" for q in queues]
            self._log.info("QUEUES: {}".format(" ".join(qmsgs)))
            await asleep_until(end_time)

    # ---- Producers / Consumers ----

    async def _connect_machine_producer(
        self,
    ) -> AsyncGenerator[UMessage[str, Node], None]:
        async with self._uow_factory() as uow:
            enabled_nodes = await uow.nodes.list_enabled()
        new_nodes = [n for n in enabled_nodes if not self._gateway.contains(n.ip)]
        for node in new_nodes:
            yield UMessage(node.ip, node)

    async def _connect_machine_consumer(self, msg: UMessage[str, Node]) -> None:
        node = msg.payload
        keys = await asyncio.get_running_loop().run_in_executor(
            None, self._config.local.get_private_keys
        )
        jump_host = self._config.remote.jump_host
        jump_username = self._config.remote.jump_username
        for cloud in self._config.clouds:
            if cloud.prefix == node.cloud:
                if cloud.jump_host and cloud.jump_username:
                    jump_host, jump_username = cloud.jump_host, cloud.jump_username

        try:
            await self._gateway.connect(
                ip=node.ip,
                username=node.username,
                client_keys=keys,
                connect_timeout=10,
                data_dir=self._config.remote.data_dir,
                engines_dir=self._config.remote.engines_dir,
                tasks_dir=self._config.remote.tasks_dir,
                jump_username=jump_username,
                jump_host=jump_host,
                port=node.port,
            )
            self._machine_connected_event.set()
        except MachineConnectionError as err:
            self._log.error("Can't connect to machine with error: %s", err)
        except Exception as err:
            self._log.error("An error occuried on remote machine creation: %s", err)

    async def _allocator_producer(
        self,
    ) -> AsyncGenerator[UMessage[int, Task], None]:
        ccap = await self._clouds_get_capacity()
        tlim = max(ccap, len(self._gateway.list_free(None)), 10)
        async with self._uow_factory() as uow:
            tasks = await uow.tasks.list_by_status({TaskStatus.TO_DO}, limit=tlim)
        if tasks:
            ids = [str(t.task_id) for t in tasks]
            self._log.debug(
                "[Orchestrator][_allocator_producer] task_ids=%s", ", ".join(ids)
            )
        for task in tasks:
            yield UMessage(task.task_id, task)

    # START_CONTRACT: Orchestrator._allocator_consumer
    #   PURPOSE: Run allocate_task for one queued task; swallow exceptions to keep the worker alive.
    #   INPUTS: { msg: UMessage[int, Task] }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Delegates all allocation side effects to allocate_task; logs and swallows any exception so the allocator worker is not killed (mirrors _deallocator_consumer).
    #   LINKS: M-APPLICATION-ALLOCATE
    # END_CONTRACT: Orchestrator._allocator_consumer
    async def _allocator_consumer(self, msg: UMessage[int, Task]) -> None:
        # START_BLOCK_ALLOCATE
        self._log.debug(
            "[Orchestrator][_allocator_consumer][ALLOCATE] task_id=%s",
            msg.id,
        )
        try:
            await allocate_task(
                task_id=msg.id,
                engines=self._engines,
                uow_factory=self._uow_factory,
                gateway=self._gateway,
                clouds=self._clouds,
                start_task_on_machine=self._start_task_on_machine,
                tracker=self._tracker,
                allocation_lock=self._allocation_lock,
            )
        except Exception as err:
            self._log.error("Allocator error for task %s: %s", msg.id, err)
        # END_BLOCK_ALLOCATE

    async def _task_consumer_producer(
        self,
    ) -> AsyncGenerator[UMessage[int, Task], None]:
        async with self._uow_factory() as uow:
            tasks = await uow.tasks.list_by_status({TaskStatus.RUNNING})
        for task in tasks:
            yield UMessage(task.task_id, task)

    # START_CONTRACT: Orchestrator._task_consumer_consumer
    #   PURPOSE: Check task machine state, record TaskAbandoned for lost nodes, or consume completed tasks.
    #   INPUTS: { msg: UMessage[int, Task], machine_not_found: Counter }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Records TaskAbandoned event for lost nodes; calls consume_task use case for free machines.
    #   LINKS: M-APPLICATION-CONSUME, M-DOMAIN-EVENTS
    # END_CONTRACT: Orchestrator._task_consumer_consumer
    async def _task_consumer_consumer(
        self, msg: UMessage[int, Task], machine_not_found: Counter
    ) -> None:
        broken_tasks_passes = 20
        task_id, task = msg.id, msg.payload
        ip = task.allocated_ip or ""
        machine = self._gateway.get_machine_state(ip)
        if machine is None:
            # START_BLOCK_MACHINE_GONE
            self._log.warning(
                "[Orchestrator][_task_consumer_consumer][MACHINE_GONE] task_id=%s ip=%s",
                task_id,
                ip,
            )
            machine_not_found.update([task_id])
            if machine_not_found[task_id] > broken_tasks_passes:
                task = task.fail("node is gone")
                task = task.record_event(
                    TaskAbandoned(
                        task_id=task.task_id,
                        webhook_url=task.context.webhook_url,
                        webhook_custom_params=task.context.webhook_custom_params,
                        node_ip=ip,
                    )
                )
                async with self._uow_factory() as uow:
                    await uow.tasks.save(task)
                    await uow.commit()
                # Drop the in-flight allocation slot so the abandoned task_id
                # can't falsely dedup a future task if task IDs ever recycle.
                self._tracker.discard(task_id)
            # END_BLOCK_MACHINE_GONE
            return

        if ip not in self._occupancy_started:
            engine = self._engines.get(task.context.engine)
            if engine:
                self._gateway.start_occupancy_check(ip, engine)
                self._occupancy_started.add(ip)
                machine = self._gateway.get_machine_state(ip)
                if machine is None:
                    return

        # START_BLOCK_CONSUME
        if machine.state == MachineState.FREE and ip in self._occupancy_started:
            self._log.debug(
                "[Orchestrator][_task_consumer][CONSUME] machine=%s task_id=%s",
                ip,
                task_id,
            )
            await consume_task(
                task_id=task_id,
                ip=ip,
                gateway=self._gateway,
                engines=self._engines,
                uow_factory=self._uow_factory,
                local_tasks_dir=self._local_tasks_dir,
                tracker=self._tracker,
            )
            self._occupancy_started.discard(ip)
        # END_BLOCK_CONSUME

    # ---- Deallocator producer-consumer ----

    # START_CONTRACT: Orchestrator._deallocator_producer
    #   PURPOSE: Find idle nodes exceeding tolerance, disable them via use case, yield disabled IPs for deallocation.
    #   INPUTS: { None }
    #   OUTPUTS: { AsyncGenerator[UMessage[str, str], None] - yields disabled cloud node IPs }
    #   SIDE_EFFECTS: Disables idle nodes in DB via deallocate_nodes use case.
    #   LINKS: M-APPLICATION-DEALLOCATE
    # END_CONTRACT: Orchestrator._deallocator_producer
    async def _deallocator_producer(
        self,
    ) -> AsyncGenerator[UMessage[str, str], None]:
        # START_BLOCK_COLLECT_IDLE
        # free_since is monotonic; pass it through unchanged so deallocate_nodes
        # compares against time.monotonic() and stays immune to wall-clock jumps.
        idle_machines: dict[str, float] = {}
        for m in self._gateway.list_connected():
            if m.state == MachineState.FREE and m.free_since is not None:
                idle_machines[m.ip] = m.free_since
        # END_BLOCK_COLLECT_IDLE

        # START_BLOCK_DEALLOCATE_USE_CASE
        disabled_ips = await deallocate_nodes(
            self._uow_factory, self._config_clouds, idle_machines
        )
        # END_BLOCK_DEALLOCATE_USE_CASE

        # START_BLOCK_YIELD_DISABLED
        for ip in disabled_ips:
            yield UMessage(ip, ip)
        # END_BLOCK_YIELD_DISABLED

    # START_CONTRACT: Orchestrator._deallocator_consumer
    #   PURPOSE: Disconnect and cloud-deallocate a single disabled node.
    #   INPUTS: { msg: UMessage[str, str] - disabled node IP }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Disconnects remote machine, deletes cloud VM.
    #   LINKS: M-APPLICATION-DEALLOCATE
    # END_CONTRACT: Orchestrator._deallocator_consumer
    async def _deallocator_consumer(self, msg: UMessage[str, str]) -> None:
        ip = msg.payload
        try:
            async with self._uow_factory() as uow:
                node = await uow.nodes.get(ip)
            if node is not None:
                await deallocate_node(
                    node, self._gateway, self._clouds, self._uow_factory
                )
            elif self._gateway.contains(ip):
                await self._gateway.disconnect(ip)
        except Exception as err:
            self._log.error("Deallocator error for %s: %s", ip, err)

    # ---- Infrastructure ----

    # START_CONTRACT: Orchestrator._clouds_get_capacity
    #   PURPOSE: Compute available cloud capacity as max(0, total_max_nodes - current_count) over active clouds.
    #   INPUTS: { None - reads self._uow_factory and self._active_clouds }
    #   OUTPUTS: { int - available node slots across all active clouds }
    #   SIDE_EFFECTS: Opens a short UoW to read yascheduler_nodes; no writes.
    #   LINKS: M-APPLICATION-UOW, M-CONFIG, M-DOMAIN-MODEL
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
                try:
                    await consumer(msg)
                finally:
                    queue.item_done(msg)

        workers: set[asyncio.Task] = set()
        for _ in range(workers_num):
            workers.add(asyncio.create_task(worker()))

        try:
            while not self._cancellation_event.is_set():
                end_time = datetime.now() + timedelta(seconds=self._sleep_interval)
                try:
                    async for msg in producer():
                        await queue.put(msg)
                finally:
                    await asleep_until(end_time)
        except asyncio.CancelledError:
            if not queue.empty():
                self._log.info(
                    "Queue %s has %s items - waiting", queue.name, queue.qsize()
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
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: Orchestrator._await_first_machine
    async def _await_first_machine(self) -> None:
        # START_BLOCK_WAIT_MACHINES
        if len(self._gateway) > 0:
            return

        async def _wait() -> None:
            await self._machine_connected_event.wait()

        wait_task = asyncio.create_task(_wait())
        timeout_task = asyncio.create_task(asyncio.sleep(30))
        done, pending = await asyncio.wait(
            [wait_task, timeout_task],
            return_when="FIRST_COMPLETED",
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        # END_BLOCK_WAIT_MACHINES

    # START_CONTRACT: Orchestrator._shutdown_barrier
    #   PURPOSE: Wait for background jobs to complete.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None
    #   LINKS:
    # END_CONTRACT: Orchestrator._shutdown_barrier
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
        self._log.debug(
            "[Orchestrator][start] engines=%s",
            ", ".join(self._engines.keys()),
        )

        self._bg_jobs.add(asyncio.create_task(self._print_stats()))

        conn_machine_co = self._create_producer_consumers(
            queue=self._conn_machine_q,
            producer=self._connect_machine_producer,
            consumer=self._connect_machine_consumer,
            workers_num=self._config.local.conn_machine_limit,
        )
        self._bg_jobs.add(asyncio.create_task(conn_machine_co))

        await self._await_first_machine()

        allocate_co = self._create_producer_consumers(
            queue=self._allocate_q,
            producer=self._allocator_producer,
            consumer=self._allocator_consumer,
            workers_num=self._config.local.allocate_limit,
        )
        self._bg_jobs.add(asyncio.create_task(allocate_co))

        machine_not_found: Counter[str] = Counter()
        consume_co = self._create_producer_consumers(
            queue=self._consume_q,
            producer=self._task_consumer_producer,
            consumer=partial(
                self._task_consumer_consumer,
                machine_not_found=machine_not_found,
            ),
            workers_num=self._config.local.consume_limit,
        )
        self._bg_jobs.add(asyncio.create_task(consume_co))

        deallocate_co = self._create_producer_consumers(
            queue=self._deallocate_q,
            producer=self._deallocator_producer,
            consumer=self._deallocator_consumer,
            workers_num=self._config.local.deallocate_limit,
        )
        self._bg_jobs.add(asyncio.create_task(deallocate_co))

        await self._shutdown_barrier()

    # START_CONTRACT: Orchestrator.stop
    #   PURPOSE: Signal the daemon to stop and clean up non-session resources.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Cancels jobs, disconnects machines, stops clouds.
    #   LINKS: M-CLOUD-PROVISIONER, M-SSH-GATEWAY
    # END_CONTRACT: Orchestrator.stop
    async def stop(self) -> None:
        self._log.info("Stopping...")
        self._cancellation_event.set()

        for task in self._bg_jobs:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self._clouds.stop()
        await self._gateway.disconnect_all()
        if self._http_session is not None:
            await self._http_session.close()
