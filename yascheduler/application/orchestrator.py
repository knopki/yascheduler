# FILE: yascheduler/application/orchestrator.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Daemon orchestrator — manages producer-consumer loops calling use cases.
#   SCOPE: Orchestrator class with start/stop lifecycle, 4 loop pairs, stats, webhook, and SSH helpers.
#   DEPENDS: M-DB, M-REMOTE-REPO, M-CLOUD-MANAGER, M-CONFIG, M-QUEUE, M-TIME
#   LINKS: M-DB, M-CONFIG, M-QUEUE, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _safe_b64decode - Decode base64 with lenient padding handling
#   _write_remote_file - Write data to remote file via SFTP with error handling
#   Orchestrator - Daemon loop manager: connect machines, allocate, consume, deallocate
#   Orchestrator._exec_spawn_command - Execute spawn command on remote machine
#   Orchestrator._await_first_machine - Wait up to 30s for first machine connection
#   Orchestrator._shutdown_barrier - Gather bg jobs and work around aiohttp close race
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.1.3 - Move aiohttp.ClientSession creation from __init__ to start() to avoid orphaned sessions.
#   PREVIOUS_CHANGE: v2.1.2 - Remove duplicate WebhookPayload; import from webhook module; drop attrs dependency in this module.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import base64
import logging
from asyncio.locks import Event, Semaphore
from collections import Counter
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path, PurePath, PurePosixPath
from typing import Any
from dataclasses import asdict

import aiohttp
import asyncssh
import backoff
from asyncssh.sftp import SFTPClient

from yascheduler.clouds import CloudAPIManager
from yascheduler.config import Config, ConfigCloud, Engine, EngineRepository
from yascheduler.db import DB, NodeModel, TaskModel, TaskStatus
from yascheduler.queue import UMessage, UniqueQueue
from yascheduler.remote_machine import (
    AllSSHRetryExc,
    RemoteMachine,
    RemoteMachineRepository,
)
from yascheduler.time import asleep_until
from yascheduler.webhook import WebhookPayload

from .allocate_task import allocate_task
from .consume_task import consume_task
from .deallocate_nodes import deallocate_node


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
#   LINKS: M-REMOTE-REPO
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
#   INPUTS: { config, db, clouds, remote_machines, engines, log, config_clouds, local_tasks_dir }
#   OUTPUTS: { Orchestrator instance }
#   SIDE_EFFECTS: Creates queues, HTTP session, cancellation event.
#   LINKS: M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE
# END_CONTRACT: Orchestrator
class Orchestrator:
    # START_CONTRACT: Orchestrator.__init__
    #   PURPOSE: Initialise orchestrator with all daemon dependencies.
    #   INPUTS: { config: Config, db: DB, clouds: CloudAPIManager, remote_machines: RemoteMachineRepository, engines: EngineRepository, log: Logger, config_clouds: Sequence[ConfigCloud], local_tasks_dir: Path }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates UniqueQueues, Semaphore. HTTP session deferred to start().
    #   LINKS: M-CONFIG, M-DB, M-QUEUE
    # END_CONTRACT: Orchestrator.__init__
    def __init__(
        self,
        config: Config,
        db: DB,
        clouds: CloudAPIManager,
        remote_machines: RemoteMachineRepository,
        engines: EngineRepository,
        log: logging.Logger,
        config_clouds: Sequence[ConfigCloud],
        local_tasks_dir: Path,
    ) -> None:
        self._config = config
        self._db = db
        self._clouds = clouds
        self._remote_machines = remote_machines
        self._engines = engines
        self._log = log
        self._config_clouds = config_clouds
        self._local_tasks_dir = local_tasks_dir

        self._bg_jobs: set[asyncio.Task[None]] = set()
        self._cancellation_event = Event()
        self._sleep_interval: int = min(e.sleep_interval for e in engines.values())

        lcfg = config.local
        self._webhook_sem = Semaphore(lcfg.webhook_reqs_limit)
        self._conn_machine_q: UniqueQueue[str, NodeModel] = UniqueQueue(
            "conn_machine", maxsize=lcfg.conn_machine_pending
        )
        self._allocate_q: UniqueQueue[int, TaskModel] = UniqueQueue(
            "allocate", maxsize=lcfg.allocate_pending
        )
        self._consume_q: UniqueQueue[int, TaskModel] = UniqueQueue(
            "consume", maxsize=lcfg.consume_pending
        )
        self._deallocate_q: UniqueQueue[str, NodeModel] = UniqueQueue(
            "deallocate", maxsize=lcfg.deallocate_pending
        )
        self._http: aiohttp.ClientSession | None = None

    # ---- SSH helpers (moved from Scheduler) ----

    # START_CONTRACT: Orchestrator._upload_task_data
    #   PURPOSE: Upload task input files to remote machine via SFTP.
    #   INPUTS: { sftp, task, remote_dir, input_files }
    #   OUTPUTS: { bool - True on success }
    #   SIDE_EFFECTS: Creates remote directories, writes files via SFTP.
    #   LINKS: M-REMOTE-REPO
    # END_CONTRACT: Orchestrator._upload_task_data
    async def _upload_task_data(
        self,
        sftp: SFTPClient,
        task: TaskModel,
        remote_dir: PurePath,
        input_files: Sequence[str],
    ) -> bool:

        # START_BLOCK_UPLOAD
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
            if input_file == "fort.9":
                await _write_remote_file(
                    sftp,
                    r_input_file.as_posix(),
                    _safe_b64decode(task.metadata[input_file]),
                    self._log,
                )
            else:
                await _write_remote_file(
                    sftp,
                    r_input_file.as_posix(),
                    task.metadata[input_file],
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
    #   LINKS: M-REMOTE-REPO, M-DB
    # END_CONTRACT: Orchestrator._exec_spawn_command
    async def _exec_spawn_command(
        self,
        machine: RemoteMachine,
        engine: Engine,
        task: TaskModel,
        task_dir: PurePath,
        eng_path: PurePath,
    ) -> None:
        # START_BLOCK_SPAWN
        try:
            node = await self._db.get_node(task.ip)
            ncpus = (node and node.ncpus) or await machine.get_cpu_cores()
            run_cmd = engine.spawn.format(
                engine_path=str(eng_path),
                task_path=machine.quote(str(task_dir)),
                ncpus=ncpus,
            )
            await machine.run_bg(run_cmd, cwd=str(task_dir))
        except Exception as err:
            self._log.error("SSH spawn cmd error: %s", err)
            raise err
        # END_BLOCK_SPAWN

    # START_CONTRACT: Orchestrator._start_task_on_machine
    #   PURPOSE: Upload inputs and spawn calculation process on remote node.
    #   INPUTS: { machine: RemoteMachine, engine: Engine, task: TaskModel }
    #   OUTPUTS: { bool - True on successful spawn }
    #   SIDE_EFFECTS: Uploads files, marks machine busy, executes spawn command.
    #   LINKS: M-REMOTE-REPO, M-DB
    # END_CONTRACT: Orchestrator._start_task_on_machine
    async def _start_task_on_machine(
        self,
        machine: RemoteMachine,
        engine: Engine,
        task: TaskModel,
    ) -> bool:
        self._log.info(
            "Submitting task_id=%s %s with %s to %s",
            task.task_id,
            task.label,
            engine.name,
            machine.hostname,
        )
        assert task.metadata.get("remote_folder")
        machine.meta.busy = True
        remote_folder = machine.path(task.metadata["remote_folder"])

        # START_BLOCK_DEPLOY
        async with machine.sftp() as sftp:
            try:
                root_dir = machine.path(await sftp.realpath("."))
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
                await self._upload_task_data(sftp, task, task_dir, engine.input_files)
            except Exception as err:
                self._log.error("Can't upload task_id=%s files: %s", task.task_id, err)
                raise err
        # END_BLOCK_DEPLOY

        await self._exec_spawn_command(machine, engine, task, task_dir, engine_path)

        return True

    # START_CONTRACT: Orchestrator._do_task_webhook
    #   PURPOSE: Send webhook notification for task status change.
    #   INPUTS: { task_id, metadata, status }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Sends HTTP POST to webhook_url.
    #   LINKS:
    # END_CONTRACT: Orchestrator._do_task_webhook
    async def _do_task_webhook(
        self,
        task_id: int,
        metadata: Mapping[str, Any],
        status: TaskStatus,
    ) -> None:
        url = metadata.get("webhook_url")
        if not url or self._http is None:
            return
        retry = backoff.on_exception(backoff.fibo, aiohttp.ClientError, max_time=60)
        async with self._webhook_sem:
            self._log.info("Executing webhook of type %s to %s", status.value, url)
            payload = WebhookPayload(
                task_id, status.value, metadata.get("webhook_custom_params", {})
            )
            try:
                async with retry(self._http.post)(url, data=asdict(payload)) as resp:  # type: ignore[arg-type]
                    if resp.ok:
                        return
                    self._log.warn(
                        "Webhook for task_id=%s bad response: %s %s",
                        task_id,
                        resp.status,
                        resp.reason,
                    )
                    if self._log.isEnabledFor(logging.DEBUG):
                        self._log.debug(
                            "Webhook for task_id=%s response: %s",
                            task_id,
                            (await resp.text("utf-8")),
                        )
            except Exception as err:
                self._log.error("Webhook for task_id=%s failed: %s", task_id, err)

    # ---- Stats ----

    # START_CONTRACT: Orchestrator._print_stats
    #   PURPOSE: Periodically log queue sizes, node counts, and task counts.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Logs statistics every 10 seconds.
    #   LINKS: M-DB
    # END_CONTRACT: Orchestrator._print_stats
    async def _print_stats(self) -> None:
        while not self._cancellation_event.is_set():
            end_time = datetime.now() + timedelta(seconds=10)
            ncounters = await self._db.count_nodes_by_status()
            tcounters = await self._db.count_tasks_by_status()
            tmpl = (
                "THREADS: {tasks} "
                "NODES: busy:{n_busy}/enabled:{n_enabled}/total:{n_total} "
                "TASKS: run:{t_run}/todo:{t_todo}/done:{t_done}"
            )
            msg = tmpl.format(
                tasks=len(asyncio.all_tasks()),
                n_busy=len(self._remote_machines.filter(busy=True).keys()),
                n_enabled=ncounters[True],
                n_total=sum(ncounters.values()),
                t_run=tcounters[TaskStatus.RUNNING],
                t_todo=tcounters[TaskStatus.TO_DO],
                t_done=tcounters[TaskStatus.DONE],
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
    ) -> AsyncGenerator[UMessage[str, NodeModel], None]:
        enabled_nodes = await self._db.get_enabled_nodes()
        new_nodes = [
            n for n in enabled_nodes if n.ip not in self._remote_machines.keys()
        ]
        for node in new_nodes:
            yield UMessage(node.ip, node)

    async def _connect_machine_consumer(self, msg: UMessage[str, NodeModel]):
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
            self._remote_machines[node.ip] = await RemoteMachine.create(
                host=node.ip,
                username=node.username,
                client_keys=keys,
                logger=self._log,
                data_dir=self._config.remote.data_dir,
                engines_dir=self._config.remote.engines_dir,
                tasks_dir=self._config.remote.tasks_dir,
                connect_timeout=10,
                jump_username=jump_username,
                jump_host=jump_host,
                port=node.port,
            )
        except asyncssh.misc.Error as err:
            self._log.error("Can't connect to machine with error: %s", err)
        except Exception as err:
            self._log.error("An error occuried on remote machine creation: %s", err)

    async def _allocator_producer(
        self,
    ) -> AsyncGenerator[UMessage[int, TaskModel], None]:
        ccap = await self._clouds_get_capacity()
        tlim = max(ccap, len(self._remote_machines.filter(busy=False)), 10)
        tasks = await self._db.get_tasks_by_status((TaskStatus.TO_DO,), tlim)
        if tasks:
            ids = [str(t.task_id) for t in tasks]
            self._log.debug("Want to allocate tasks: %s", ", ".join(ids))
        for task in tasks:
            yield UMessage(task.task_id, task)

    @backoff.on_exception(backoff.fibo, AllSSHRetryExc, max_time=60)
    async def _allocator_consumer(self, msg: UMessage[int, TaskModel]):
        # START_BLOCK_ALLOCATE
        await allocate_task(
            task=msg.payload,
            engines=self._engines,
            db=self._db,
            remote_machines=self._remote_machines,
            clouds=self._clouds,
            start_task_on_machine=self._start_task_on_machine,
            do_task_webhook=self._do_task_webhook,
        )
        # END_BLOCK_ALLOCATE

    async def _task_consumer_producer(
        self,
    ) -> AsyncGenerator[UMessage[int, TaskModel], None]:
        tasks = await self._db.get_tasks_by_status((TaskStatus.RUNNING,))
        for task in tasks:
            yield UMessage(task.task_id, task)

    async def _task_consumer_consumer(
        self, msg: UMessage[int, TaskModel], machine_not_found: Counter
    ):
        broken_tasks_passes = 20
        task_id, task = msg.id, msg.payload
        machine = self._remote_machines.get(task.ip)
        if machine is None:
            self._log.warning("Task %s - machine %s is gone", task_id, task.ip)
            machine_not_found.update([task_id])
            if machine_not_found[task_id] > broken_tasks_passes:
                await self._db.set_task_error(
                    task_id, metadata=task.metadata, error="node is gone"
                )
                await self._do_task_webhook(task_id, task.metadata, TaskStatus.DONE)
            return
        if machine.meta.busy is None:
            engine = self._engines.get(task.metadata["engine"])
            if engine:
                await machine.start_occupancy_check(engine)
        # START_BLOCK_CONSUME
        if machine.meta.busy is False:
            self._log.debug("machine %s is free of task %s", machine.hostname, task_id)
            await consume_task(
                machine=machine,
                task=task,
                engines=self._engines,
                db=self._db,
                local_tasks_dir=self._local_tasks_dir,
                clouds=self._clouds,
                do_task_webhook=self._do_task_webhook,
            )
        # END_BLOCK_CONSUME

    # ---- Deallocator producer-consumer ----

    # START_CONTRACT: Orchestrator._deallocator_producer
    #   PURPOSE: Find idle nodes exceeding tolerance, disable them, yield disabled nodes for deallocation.
    #   INPUTS: { None }
    #   OUTPUTS: { AsyncGenerator[UMessage[str, NodeModel], None] - yields disabled cloud nodes }
    #   SIDE_EFFECTS: Disables idle nodes in DB.
    #   LINKS: M-APPLICATION-DEALLOCATE
    # END_CONTRACT: Orchestrator._deallocator_producer
    async def _deallocator_producer(
        self,
    ) -> AsyncGenerator[UMessage[str, NodeModel], None]:
        # START_BLOCK_DISABLE_IDLE
        tasks = await self._db.get_tasks_by_status((TaskStatus.RUNNING,))
        busy_ips = [t.ip for t in tasks]
        all_enabled_nodes = {
            n.ip: n for n in await self._db.get_enabled_nodes() if n.ip not in busy_ips
        }
        for ccfg in self._config_clouds:
            tdlim = timedelta(seconds=ccfg.idle_tolerance)
            idlers = self._remote_machines.filter(
                busy=False, reverse_sort=False, free_since_gt=tdlim
            )
            nodes_to_disable = [
                ip
                for ip, node in all_enabled_nodes.items()
                if node.cloud == ccfg.prefix and ip in idlers.keys()
            ]
            for ip in nodes_to_disable:
                await self._db.disable_node(ip)
                await self._db.commit()
        # END_BLOCK_DISABLE_IDLE

        # START_BLOCK_COLLECT_DEALLOCATE
        free_disabled_nodes = [
            node
            for node in await self._db.get_disabled_nodes()
            if node.ip not in busy_ips and "." in node.ip and node.cloud
        ]
        for node in free_disabled_nodes:
            yield UMessage(node.ip, node)
        # END_BLOCK_COLLECT_DEALLOCATE

    # START_CONTRACT: Orchestrator._deallocator_consumer
    #   PURPOSE: Disconnect and cloud-deallocate a single node.
    #   INPUTS: { msg: UMessage[str, NodeModel] - node to deallocate }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Disconnects remote machine, deletes cloud VM.
    #   LINKS: M-APPLICATION-DEALLOCATE
    # END_CONTRACT: Orchestrator._deallocator_consumer
    async def _deallocator_consumer(self, msg: UMessage[str, NodeModel]):
        try:
            await deallocate_node(msg.payload, self._remote_machines, self._clouds)
        except Exception as err:
            self._log.error("Deallocator error for node %s: %s", msg.id, err)

    # ---- Infrastructure ----

    async def _clouds_get_capacity(self) -> int:
        ccap = await self._clouds.get_capacity()
        n_busy_cloud_nodes = sum(x.current for x in ccap.values())
        max_nodes = sum(x.config.max_nodes for x in self._clouds.apis.values())
        diff = max_nodes - n_busy_cloud_nodes
        return max(0, diff)

    async def _create_producer_consumers(
        self,
        queue: UniqueQueue,
        producer: Callable,
        consumer: Callable,
        workers_num: int = 1,
    ) -> None:
        async def worker():
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
    #   LINKS: M-REMOTE-REPO
    # END_CONTRACT: Orchestrator._await_first_machine
    async def _await_first_machine(self) -> None:
        # START_BLOCK_WAIT_MACHINES
        async def _wait():
            while not len(self._remote_machines):
                await asyncio.sleep(1)

        await asyncio.wait(
            [asyncio.create_task(x) for x in [_wait(), asyncio.sleep(30)]],
            return_when="FIRST_COMPLETED",
        )
        # END_BLOCK_WAIT_MACHINES

    # START_CONTRACT: Orchestrator._shutdown_barrier
    #   PURPOSE: Wait for background jobs and work around aiohttp session close race.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Sleeps 1s to avoid Unclosed client session warning.
    #   LINKS:
    # END_CONTRACT: Orchestrator._shutdown_barrier
    async def _shutdown_barrier(self) -> None:
        await asyncio.gather(*self._bg_jobs, return_exceptions=True)
        await asyncio.sleep(1)  # workaround aiohttp's Unclosed client session

    # START_CONTRACT: Orchestrator.start
    #   PURPOSE: Start all producer-consumer loops for the daemon.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates aiohttp session, background tasks, connects machines, starts all producer-consumer loops (allocate/consume/deallocate) with config-limited concurrency.
    #   LINKS: M-QUEUE, M-DB
    # END_CONTRACT: Orchestrator.start
    async def start(self) -> None:
        self._log.debug(
            "Available computing engines: %s",
            ", ".join(self._engines.keys()),
        )

        self._http = aiohttp.ClientSession()
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
    #   PURPOSE: Graceful shutdown of all background tasks and connections.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Cancels jobs, disconnects machines, stops clouds, closes HTTP.
    #   LINKS: M-CLOUD-MANAGER, M-REMOTE-REPO
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
        await self._remote_machines.disconnect_all()
        if self._http is not None:
            await self._http.close()
