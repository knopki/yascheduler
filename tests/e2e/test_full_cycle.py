# FILE: tests/e2e/test_full_cycle.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: E2E test exercising full scheduler lifecycle against real PostgreSQL and SSH.
#   SCOPE: Single test — node add → submit → allocate → spawn → consume → verify.
#   DEPENDS: M-DB, M-CONFIG, M-APPLICATION-ORCHESTRATOR, M-DI, M-SSH-GATEWAY
#   LINKS: M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_full_cycle - Full scheduler lifecycle E2E test with node BUSY→FREE transition verification
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.1 - Update get_machine_state assertions for new ConnectedMachine return contract (gateway-port-cleanup).
#   PREVIOUS_CHANGE: v1.0.0 - Add full lifecycle E2E test.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from yascheduler.adapters.ssh.gateway import SSHMachineGateway
from yascheduler.db import DB, TaskStatus
from yascheduler.di import make_cli_deps, make_daemon
from yascheduler.domain.model import MachineState

if TYPE_CHECKING:
    from yascheduler.config import Config

log = logging.getLogger("e2e.test_full_cycle")


async def test_full_cycle(
    e2e_config: Config,
    db: DB,
    ssh_container: dict[str, Any],
) -> None:
    config = e2e_config

    # START_BLOCK_ADD_NODE
    gateway = SSHMachineGateway(log=log)
    machine = await gateway.connect(
        ip=ssh_container["host"],
        username=ssh_container["username"],
        client_keys=[ssh_container["key_path"]],
        port=ssh_container["port"],
        data_dir=config.remote.data_dir,
        engines_dir=config.remote.engines_dir,
        tasks_dir=config.remote.tasks_dir,
    )
    await gateway.setup_node(ssh_container["host"], config.engines)

    engines_dir = gateway.get_engines_dir(ssh_container["host"])
    proc = await gateway.run(machine, f"test -f {engines_dir}/test_shell/run.sh")
    assert proc.exit_code == 0, (
        f"Engine script not deployed at {engines_dir}/test_shell/run.sh"
    )

    await gateway.disconnect(ssh_container["host"])

    await db.add_node(
        ip_addr=ssh_container["host"],
        username=ssh_container["username"],
        port=ssh_container["port"],
        enabled=True,
    )
    await db.commit()
    # END_BLOCK_ADD_NODE

    # START_BLOCK_SUBMIT
    deps = make_cli_deps(config)
    task_id = await deps.submit("e2e test", {"1.input": "hello e2e"}, "test_shell")
    assert task_id > 0
    task_pre = await db.get_task(task_id)
    assert task_pre is not None and task_pre.status == TaskStatus.TO_DO
    # END_BLOCK_SUBMIT

    # START_BLOCK_RUN_ORCHESTRATOR
    orchestrator = await make_daemon(config, db=db)
    orch_task = asyncio.create_task(orchestrator.start())
    # END_BLOCK_RUN_ORCHESTRATOR

    try:
        # START_BLOCK_POLL
        task = None
        saw_running = False
        saw_busy = False
        for _ in range(60):
            task = await db.get_task(task_id)
            if task and task.status == TaskStatus.RUNNING:
                saw_running = True
                node_ip = task.ip
                state = orchestrator._gateway.get_machine_state(node_ip)
                if state and state.state == MachineState.BUSY:
                    saw_busy = True
            if task and task.status == TaskStatus.DONE:
                break
            await asyncio.sleep(0.5)
        else:
            pytest.fail("Task did not complete within 30s")
        # END_BLOCK_POLL

        # START_BLOCK_VERIFY
        assert task is not None
        assert task.status == TaskStatus.DONE
        assert task.ip == ssh_container["host"]
        assert saw_running, "Task never reached RUNNING state"
        assert saw_busy, "Machine was never observed busy during task execution"

        local_folder = task.metadata.get("local_folder")
        assert local_folder, "Task metadata missing local_folder"
        output_file = Path(str(local_folder)) / "1.input.out"
        assert output_file.exists(), f"Output file not found: {output_file}"
        assert output_file.read_text() == "hello e2e"
        # END_BLOCK_VERIFY

        # START_BLOCK_VERIFY_FREE
        state = orchestrator._gateway.get_machine_state(ssh_container["host"])
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
        await db.remove_node(ssh_container["host"])
        # END_BLOCK_CLEANUP
