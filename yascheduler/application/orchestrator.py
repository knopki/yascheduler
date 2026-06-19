# FILE: yascheduler/application/orchestrator.py
# VERSION: 4.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Daemon orchestrator — manages producer-consumer loops calling use cases.
#   SCOPE: Orchestrator class with start/stop lifecycle, 4 loop pairs, stats, and SSH helpers.
#   DEPENDS: M-APPLICATION-UOW, M-CONFIG, M-QUEUE, M-TIME, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-SSH-GATEWAY, M-DOMAIN-MODEL, M-DOMAIN-EVENTS
#   LINKS: M-CONFIG, M-QUEUE, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-APPLICATION-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _safe_b64decode - Decode base64 with lenient padding handling
#   _write_remote_file - Write data to remote file via SFTP with error handling
#   Orchestrator - Daemon loop manager: connect machines, allocate, consume, deallocate
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v4.0.0 - Remove _do_task_webhook; record TaskAbandoned event instead of direct webhook call.
#   PREVIOUS_CHANGE: v3.0.0 - Replace RemoteMachineRepository/RemoteMachine with SSHMachineGateway/ConnectedMachine.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import base64
import logging  # noqa: TC003 — used at runtime for log calls
import time
from asyncio.locks import Event
from collections import Counter
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path, PurePath, PurePosixPath
from typing import TYPE_CHECKING

import asyncssh
import backoff

from yascheduler.adapters import AllSSHRetryExc
from yascheduler.domain import (
    ConnectedMachine,
    MachineState,
    Node,
    Task,
    TaskAbandoned,
    TaskStatus,
)
from yascheduler.queue import UMessage, UniqueQueue
from yascheduler.time import asleep_until

from .allocate_task import allocate_task
from .consume_task import consume_task
from .deallocate_nodes import deallocate_node, deallocate_nodes

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence

    import aiohttp
    from asyncssh.sftp import SFTPClient

    from yascheduler.adapters import CloudProvisionerImpl, SSHMachineGateway
    from yascheduler.config import Config, ConfigCloud, Engine, EngineRepository

    from .uow import AbstractUnitOfWork


# START_CONTRACT: _safe_b64decode
#   PURPOSE: Decode base64 string with lenient padding handling.
#   INPUTS: { b64_data: str | bytes - base64 encoded data }
#   OUTPUTS: { bytes - decoded binary data }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: _safe_b64decode
def _safe_b64decode(b64_data: str | bytes) -> bytes:
    if isinstance(b64_data, bytes):
        b64_data = b64_data.decode()
    b64_data = b64_data.strip().replace("\n", "").replace(" ", "")
    missing_padding = len(b64_data) % 4
    if missing_padding:
        b64_data += "=" * (4 - missing_padding)
    return base64.b64decode(b64_data)


# START_CONTRACT: _write_remote_file
#   PURPOSE: Write data to a remote file via SFTP with error handling.
#   INPUTS: { sftp: SFTPClient, path: str, data: bytes | str, log: Logger, mode: str }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Writes file on remote machine.
#   LINKS: M-SSH-GATEWAY
# END_CONTRACT: _write_remote_file
async def _write_remote_file(
    sftp: SFTPClient,
    path: str,
    data: bytes | str,
    log: logging.Logger,
    mode: str = "wb",
) -> None:
    # START_BLOCK_WRITE_FILE
    try:
        async with sftp.open(path, mode) as f:
            await f.write(data)  # type: ignore[type-var]
    except asyncssh.misc.Error as err:
        log.error(
            "Write %s - SFTPError: %s (%s)",
            path,
            err.reason,
            err.code,
        )
        raise err
    except Exception as e:
        log.error("Error processing file %s: %s", path, e)
    # END_BLOCK_WRITE_FILE


# START_CONTRACT: Orchestrator
#   PURPOSE: Manage the daemon's 4 producer-consumer loops, delegating business logic to use cases.
#   INPUTS: { config, uow_factory, clouds, gateway, engines, log, config_clouds, local_tasks_dir }
#   OUTPUTS: { Orchestrator instance }
#   SIDE_EFFECTS: Creates queues, cancellation event.
#   LINKS: M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-APPLICATION-UOW
# END_CONTRACT: Orchestrator
class Orchestrator:
    # START_CONTRACT: Orchestrator.__init__
    #   PURPOSE: Initialise orchestrator with all daemon dependencies.
    #   INPUTS: { config: Config, uow_factory: Callable[[], AbstractUnitOfWork], clouds: CloudProvisionerImpl, gateway: SSHMachineGateway, engines: EngineRepository, log: Logger, config_clouds: Sequence[ConfigCloud], local_tasks_dir: Path }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates UniqueQueues.
    #   LINKS: M-CONFIG, M-APPLICATION-UOW, M-QUEUE, M-SSH-GATEWAY
    # END_CONTRACT: Orchestrator.__init__
    def __init__(
        self,
        config: Config,
        uow_factory: Callable[[], AbstractUnitOfWork],
        clouds: CloudProvisionerImpl,
        gateway: SSHMachineGateway,
        engines: EngineRepository,
        log: logging.Logger,
        config_clouds: Sequence[ConfigCloud],
        local_tasks_dir: Path,
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

    # ---- SSH helpers ----

    # START_CONTRACT: Orchestrator._upload_task_data
    #   PURPOSE: Upload task input files to remote machine via SFTP.
    #   INPUTS: { gateway, ip, task, remote_dir, input_files }
    #   OUTPUTS: { bool - True on success }
    #   SIDE_EFFECTS: Creates remote directories, writes files via SFTP.
    #   LINKS: M-SSH-GATEWAY
    # END_CONTRACT: Orchestrator._upload_task_data
    async def _upload_task_data(
        self,
        gateway: SSHMachineGateway,
        ip: str,
        task: Task,
        remote_dir: PurePath,
        input_files: Sequence[str],
    ) -> bool:

        # START_BLOCK_UPLOAD
        async with gateway.get_sftp(ip) as sftp:
            try:
                await sftp.makedirs(PurePosixPath(remote_dir), exist_ok=True)
            except asyncssh.misc.Error as err:
                self._log.error(
                    "Create %s - SFTPError: %s (%s) (task_id=%s)",
                    remote_dir,
                    err.reason,
                    err.code,
                    task.task_id,
                )
                raise err

            for input_file in input_files:
                r_input_file = remote_dir / input_file
                file_data = task.context.extra[input_file]
                if input_file == "fort.9":
                    await _write_remote_file(
                        sftp,
                        r_input_file.as_posix(),
                        _safe_b64decode(str(file_data)),
                        self._log,
                    )
                else:
                    await _write_remote_file(
                        sftp,
                        r_input_file.as_posix(),
                        str(file_data),
                        self._log,
                        mode="w",
                    )
        return True
        # END_BLOCK_UPLOAD

    # START_CONTRACT: Orchestrator._exec_spawn_command
    #   PURPOSE: Execute spawn command on remote machine via SSH.
    #   INPUTS: { machine, engine, task, task_dir, eng_path }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Runs background process on remote machine.
    #   LINKS: M-SSH-GATEWAY, M-APPLICATION-UOW
    # END_CONTRACT: Orchestrator._exec_spawn_command
    async def _exec_spawn_command(
        self,
        machine: ConnectedMachine,
        engine: Engine,
        task: Task,
        task_dir: PurePath,
        eng_path: PurePath,
    ) -> None:
        # START_BLOCK_SPAWN
        try:
            async with self._uow_factory() as uow:
                node = await uow.nodes.get(task.allocated_ip or "")
            ncpus = (node and node.ncpus) or await self._gateway.get_cpu_cores(
                machine.ip
            )
            run_cmd = engine.spawn.format(
                engine_path=str(eng_path),
                task_path=self._gateway.get_quote(machine.ip)(str(task_dir)),
                ncpus=ncpus,
            )
            await self._gateway.run_bg(machine, run_cmd, cwd=str(task_dir))
        except Exception as err:
            self._log.error("SSH spawn cmd error: %s", err)
            raise err
        # END_BLOCK_SPAWN

    # START_CONTRACT: Orchestrator._start_task_on_machine
    #   PURPOSE: Upload inputs and spawn calculation process on remote node.
    #   INPUTS: { machine: ConnectedMachine, engine: Engine, task: Task }
    #   OUTPUTS: { bool - True on successful spawn }
    #   SIDE_EFFECTS: Uploads files, marks machine busy, executes spawn command.
    #   LINKS: M-SSH-GATEWAY, M-APPLICATION-UOW
    # END_CONTRACT: Orchestrator._start_task_on_machine
    async def _start_task_on_machine(
        self,
        machine: ConnectedMachine,
        engine: Engine,
        task: Task,
    ) -> bool:
        self._log.info(
            "Submitting task_id=%s %s with %s to %s",
            task.task_id,
            task.label,
            engine.name,
            self._gateway.get_hostname(machine.ip),
        )
        assert task.context.remote_folder is not None
        self._gateway.update_machine(machine.occupy())
        path_type = self._gateway.get_path(machine.ip)
        remote_folder = path_type(task.context.remote_folder)

        # START_BLOCK_DEPLOY
        async with self._gateway.get_sftp(machine.ip) as sftp:
            try:
                root_dir = path_type(await sftp.realpath("."))
                task_dir = (
                    remote_folder
                    if remote_folder.is_absolute()
                    else root_dir / remote_folder
                )
                if self._config.remote.engines_dir.is_absolute():
                    engine_path = self._config.remote.engines_dir / engine.name
                else:
                    engine_path = (
                        root_dir / self._config.remote.engines_dir / engine.name
                    )
                await self._upload_task_data(
                    self._gateway, machine.ip, task, task_dir, engine.input_files
                )
            except Exception as err:
                self._log.error("Can't upload task_id=%s files: %s", task.task_id, err)
                raise err
        # END_BLOCK_DEPLOY

        await self._exec_spawn_command(machine, engine, task, task_dir, engine_path)

        return True

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
                for s in self._gateway.items()
                if s[1].machine.state == MachineState.BUSY
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
        except asyncssh.misc.Error as err:
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

    @backoff.on_exception(backoff.fibo, AllSSHRetryExc, max_time=60)
    async def _allocator_consumer(self, msg: UMessage[int, Task]) -> None:
        # START_BLOCK_ALLOCATE
        await allocate_task(
            task_id=msg.id,
            engines=self._engines,
            uow_factory=self._uow_factory,
            gateway=self._gateway,
            clouds=self._clouds,
            start_task_on_machine=self._start_task_on_machine,
        )
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
        state = self._gateway.get_machine_state(ip)
        if state is None:
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
            # END_BLOCK_MACHINE_GONE
            return

        machine = state.machine
        if ip not in self._occupancy_started:
            engine = self._engines.get(task.context.engine)
            if engine:
                self._gateway.start_occupancy_check(ip, engine)
                self._occupancy_started.add(ip)
                state = self._gateway.get_machine_state(ip)
                if state is not None:
                    machine = state.machine

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
                clouds=self._clouds,
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
        idle_machines: dict[str, datetime] = {}
        for ip, state in self._gateway.items():
            m = state.machine
            if m.state == MachineState.FREE and m.free_since is not None:
                elapsed = time.monotonic() - m.free_since
                idle_machines[ip] = datetime.now() - timedelta(seconds=elapsed)
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
                await deallocate_node(node, self._gateway, self._clouds)
            elif self._gateway.contains(ip):
                await self._gateway.disconnect(ip)
        except Exception as err:
            self._log.error("Deallocator error for %s: %s", ip, err)

    # ---- Infrastructure ----

    async def _clouds_get_capacity(self) -> int:
        ccap = await self._clouds.get_capacity()
        n_busy_cloud_nodes = sum(x.current for x in ccap.values())
        max_nodes = sum(c.max_nodes for c in self._clouds.configs.values())
        diff = max_nodes - n_busy_cloud_nodes
        return max(0, diff)

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
