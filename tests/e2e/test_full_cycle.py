# FILE: tests/e2e/test_full_cycle.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: E2E test exercising full scheduler lifecycle against real PostgreSQL and SSH.
#   SCOPE: Single test — node add → submit → allocate → spawn → consume → verify.
#   DEPENDS: M-CONFIG, M-APPLICATION-ORCHESTRATOR, M-DI, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-PERSISTENCE-UOW, M-DOMAIN-MODEL
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-PERSISTENCE-UOW, M-DOMAIN-MODEL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_full_cycle - Full scheduler lifecycle E2E test with node BUSY→FREE transition verification
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Mark the e2e node as cloud-provisioned (cloud="e2e") so the orchestrator's connect-machine producer yields it; fix-never-connected-node-leak excluded static (cloud=None) nodes from the connect path, which silently broke this test (task stuck in TO_DO, never allocated).
#   PREVIOUS_CHANGE: v1.1.0 - Migrate from DB facade to PostgresUnitOfWork (remove-legacy-db).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from yascheduler.domain.model import MachineState, Node
from yascheduler.domain.model import TaskStatus as DomainTaskStatus
from yascheduler.entrypoints.di import make_cli_deps, make_daemon
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.repository import SSHMachineRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.entrypoints import Config
    from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

log = logging.getLogger("e2e.test_full_cycle")


async def test_full_cycle(
    e2e_config: Config,
    uow_factory: Callable[[], PostgresUnitOfWork],
    ssh_container: dict[str, Any],
) -> None:
    config = e2e_config

    # START_BLOCK_ADD_NODE
    repository = SSHMachineRepository(log=log)
    operations = SSHMachineOperations(repository=repository)
    machine = await repository.connect(
        ip=ssh_container["host"],
        username=ssh_container["username"],
        client_keys=[ssh_container["key_path"]],
        port=ssh_container["port"],
        data_dir=config.remote.data_dir,
        engines_dir=config.remote.engines_dir,
        tasks_dir=config.remote.tasks_dir,
    )
    await operations.setup_node(ssh_container["host"], config.engines)

    engines_dir = repository.get_engines_dir(ssh_container["host"])
    proc = await operations.run(machine, f"test -f {engines_dir}/test_shell/run.sh")
    assert proc.exit_code == 0, (
        f"Engine script not deployed at {engines_dir}/test_shell/run.sh"
    )

    await repository.disconnect(ssh_container["host"])

    async with uow_factory() as uow:
        await uow.nodes.add(
            Node(
                ip=ssh_container["host"],
                username=ssh_container["username"],
                port=ssh_container["port"],
                enabled=True,
                ncpus=0,
                # fix-never-connected-node-leak excluded static nodes
                # (cloud is None) from the connect-machine producer so they
                # cannot be auto-removed by the abandon path. The e2e flow
                # relies on the orchestrator connecting this node, so mark it
                # as cloud-provisioned; _connect_grace_for falls back to 120s
                # for unknown cloud prefixes and the SSH connect succeeds.
                cloud="e2e",
            )
        )
        await uow.commit()
    # END_BLOCK_ADD_NODE

    # START_BLOCK_SUBMIT
    deps = make_cli_deps(config)
    task_id = await deps.submit("e2e test", {"1.input": "hello e2e"}, "test_shell")
    assert task_id > 0
    async with uow_factory() as uow:
        task_pre = await uow.tasks.get(task_id)
    assert task_pre is not None and task_pre.status == DomainTaskStatus.TO_DO
    # END_BLOCK_SUBMIT

    # START_BLOCK_RUN_ORCHESTRATOR
    orchestrator = await make_daemon(config)
    orch_task = asyncio.create_task(orchestrator.start())
    # END_BLOCK_RUN_ORCHESTRATOR

    try:
        # START_BLOCK_POLL
        task = None
        saw_running = False
        saw_busy = False
        for _ in range(60):
            async with uow_factory() as uow:
                task = await uow.tasks.get(task_id)
            if task and task.status == DomainTaskStatus.RUNNING:
                saw_running = True
                node_ip = task.allocated_ip
                if node_ip is not None:
                    state = orchestrator._repository.get_machine_state(node_ip)
                    if state and state.state == MachineState.BUSY:
                        saw_busy = True
            if task and task.status == DomainTaskStatus.DONE:
                break
            await asyncio.sleep(0.5)
        else:
            pytest.fail("Task did not complete within 30s")
        # END_BLOCK_POLL

        # START_BLOCK_VERIFY
        assert task is not None
        assert task.status == DomainTaskStatus.DONE
        assert task.allocated_ip == ssh_container["host"]
        assert saw_running, "Task never reached RUNNING state"
        assert saw_busy, "Machine was never observed busy during task execution"

        local_folder = task.context.local_folder
        assert local_folder, "Task metadata missing local_folder"
        output_file = Path(str(local_folder)) / "1.input.out"
        assert output_file.exists(), f"Output file not found: {output_file}"
        assert output_file.read_text() == "hello e2e"
        # END_BLOCK_VERIFY

        # START_BLOCK_VERIFY_FREE
        state = orchestrator._repository.get_machine_state(ssh_container["host"])
        assert state is not None, "Machine not found in orchestrator registry"
        assert state.state == MachineState.FREE, (
            "Machine should be free after task completion"
        )
        # END_BLOCK_VERIFY_FREE

    finally:
        # START_BLOCK_CLEANUP
        await orchestrator.stop()
        try:
            await asyncio.wait_for(orch_task, timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            orch_task.cancel()
        async with uow_factory() as uow:
            await uow.nodes.remove(ssh_container["host"])
            await uow.commit()
        # END_BLOCK_CLEANUP
