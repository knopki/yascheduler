# FILE: tests/e2e/test_consume_retry.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: E2E tests for consume_task retry/permanent/regression flows (fix-download-rmtree-data-loss).
#   SCOPE: retry-then-success (transient then success), permanent->DONE+error, data-loss regression (remote dir preserved on transient).
#   DEPENDS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-CONSUME, M-SSH-OPS-DOWNLOAD, M-PERSISTENCE-UOW, M-DOMAIN-MODEL
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-CONSUME, M-SSH-OPS-DOWNLOAD, M-PERSISTENCE-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_consume_retry_then_success - First download_outputs returns transient errors -> stays RUNNING; second succeeds -> DONE, rmtree ran
#   test_consume_permanent_marks_done_with_error - download_outputs returns permanent errors -> DONE+error, rmtree ran
#   test_consume_transient_preserves_remote_dir_regression - On transient errors the remote dir still exists after consume_task returns False
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - fix-static-node-connect-exclusion: drop the `cloud="e2e"` workaround (added in v1.1.0 to mask the v6.2.1 over-broad producer filter that excluded static nodes from the connect path). The orchestrator now connects static (cloud=None) nodes again; the e2e flow exercises the real static-node production path.
#   PREVIOUS_CHANGE: v1.2.0 - session-based-machine-handle section 7.x: Migrate monkey-patched download_outputs signatures from ip to session. Capture session from connect for setup_node/open_sftp/path access.
#   PREVIOUS_CHANGE: v1.0.0 - Initial e2e tests for consume_task retry/permanent/regression flows (fix-download-rmtree-data-loss).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from asyncssh.sftp import SFTPFailure

from yascheduler.domain.model import NewNode, Node, NodeId, Task, TaskId
from yascheduler.domain.model import TaskStatus as DomainTaskStatus
from yascheduler.entrypoints.di import make_cli_deps, make_daemon
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.repository import SSHMachineRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.application.orchestrator import Orchestrator
    from yascheduler.domain import MachineSession
    from yascheduler.entrypoints import Config
    from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

log = logging.getLogger("e2e.test_consume_retry")


async def _setup_node_and_submit(
    e2e_config: Config,
    uow_factory: Callable[[], PostgresUnitOfWork],
    ssh_container: dict[str, Any],
) -> TaskId:
    """Connect, deploy engine, add node row, submit a task. Returns task_id."""
    async with uow_factory() as uow:
        db_node = await uow.nodes.insert(
            NewNode(
                ip=ssh_container["host"],
                username=ssh_container["username"],
                port=ssh_container["port"],
                enabled=True,
                ncpus=0,
            )
        )
        await uow.commit()

    repository = SSHMachineRepository(log=log)
    operations = SSHMachineOperations(repository=repository)
    session = await repository.connect(
        node=db_node,
        username=ssh_container["username"],
        client_keys=[ssh_container["key_path"]],
        port=ssh_container["port"],
        data_dir=e2e_config.remote.data_dir,
        engines_dir=e2e_config.remote.engines_dir,
        tasks_dir=e2e_config.remote.tasks_dir,
    )
    await operations.setup_node(session, e2e_config.engines)
    await repository.disconnect(db_node.node_id)

    deps = make_cli_deps(e2e_config)
    task_id = await deps.submit(
        "e2e retry test", {"1.input": "hello e2e"}, "test_shell"
    )
    assert task_id.value > 0
    return task_id


async def _wait_status(
    uow_factory: Callable[[], PostgresUnitOfWork],
    task_id: TaskId,
    target: DomainTaskStatus,
    timeout_s: float = 30.0,
) -> Task | None:
    """Poll until task reaches target status or timeout. Returns the task."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    task = None
    while asyncio.get_running_loop().time() < deadline:
        async with uow_factory() as uow:
            task = await uow.tasks.get(task_id)
        if task and task.status == target:
            return task
        await asyncio.sleep(0.5)
    return task


async def test_consume_retry_then_success(
    e2e_config: Config,
    uow_factory: Callable[[], PostgresUnitOfWork],
    ssh_container: dict[str, Any],
) -> None:
    """A RUNNING task whose first download_outputs returns transient errors
    (remote dir preserved) succeeds on the second consume cycle -> task DONE,
    remote dir removed, TaskCompleted recorded."""
    task_id = await _setup_node_and_submit(e2e_config, uow_factory, ssh_container)

    orchestrator = await make_daemon(e2e_config)

    # Install the download_outputs wrapper BEFORE starting the orchestrator so
    # the first consume cycle hits the patched impl (no timing race where the
    # real download runs first and finalises the task).
    real_download = orchestrator._operations.download_outputs
    call_count = {"n": 0}
    target_task_id = task_id

    async def flaky_download_outputs(
        session: MachineSession,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: TaskId | None = None,
    ) -> tuple[
        list[tuple[str, Any]],
        list[tuple[str | None, Exception]],
        list[tuple[str | None, Exception]],
    ]:
        if task_id is not None and task_id == target_task_id and call_count["n"] == 0:
            call_count["n"] += 1
            # Transient-only: remote dir must be preserved (rmtree gated)
            return (
                [],
                [("/remote/transient", SFTPFailure("transient blip"))],
                [],
            )
        call_count["n"] += 1
        return await real_download(
            session=session,
            remote_dir=remote_dir,
            local_dir=local_dir,
            files=files,
            task_id=task_id,
        )

    orchestrator._operations.download_outputs = flaky_download_outputs  # type: ignore[method-assign]

    orch_task = asyncio.create_task(orchestrator.start())

    try:
        # Wait until the task reaches DONE (first consume defers on transient,
        # second consume delegates to real_download and succeeds).
        task = await _wait_status(uow_factory, task_id, DomainTaskStatus.DONE)

        assert task is not None, "Task did not reach DONE"
        assert task.status == DomainTaskStatus.DONE
        assert task.context.error is None, (
            f"Expected no error on retry-then-success, got: {task.context.error}"
        )
        local_folder = task.context.local_folder
        assert local_folder, "Task metadata missing local_folder"
        output_file = Path(str(local_folder)) / "1.input.out"
        assert output_file.exists(), f"Output file not found: {output_file}"
        assert output_file.read_text() == "hello e2e"
    finally:
        await _stop_orchestrator(orchestrator, orch_task)
        await _cleanup_node(uow_factory, ssh_container)


async def test_consume_permanent_marks_done_with_error(
    e2e_config: Config,
    uow_factory: Callable[[], PostgresUnitOfWork],
    ssh_container: dict[str, Any],
) -> None:
    """A RUNNING task whose download_outputs returns permanent errors
    (e.g. missing output file) -> task DONE+error, remote dir removed,
    TaskFailed recorded."""
    task_id = await _setup_node_and_submit(e2e_config, uow_factory, ssh_container)

    orchestrator = await make_daemon(e2e_config)

    # Install the permanent-error patch BEFORE start() to avoid a timing race
    # where the real download runs first and finalises the task successfully.
    async def permanent_download_outputs(
        session: MachineSession,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: TaskId | None = None,
    ) -> tuple[
        list[tuple[str, Any]],
        list[tuple[str | None, Exception]],
        list[tuple[str | None, Exception]],
    ]:
        # Permanent-only: missing output file (bare OSError is permanent)
        return (
            [],
            [],
            [("/remote/1.input.out", OSError("No such file"))],
        )

    orchestrator._operations.download_outputs = permanent_download_outputs  # type: ignore[method-assign]

    orch_task = asyncio.create_task(orchestrator.start())

    try:
        task = await _wait_status(uow_factory, task_id, DomainTaskStatus.DONE)

        assert task is not None, "Task did not reach DONE"
        assert task.status == DomainTaskStatus.DONE
        assert task.context.error is not None, (
            "Expected error on permanent download failure"
        )
        assert "No such file" in str(task.context.error)
    finally:
        await _stop_orchestrator(orchestrator, orch_task)
        await _cleanup_node(uow_factory, ssh_container)


async def test_consume_transient_preserves_remote_dir_regression(
    e2e_config: Config,
    uow_factory: Callable[[], PostgresUnitOfWork],
    ssh_container: dict[str, Any],
) -> None:
    """Regression: when download_outputs returns transient errors, the remote
    directory still exists after consume_task returns False (the original bug
    would have rmtree'd it, losing undownloaded outputs irrecoverably)."""
    task_id = await _setup_node_and_submit(e2e_config, uow_factory, ssh_container)

    orchestrator = await make_daemon(e2e_config)

    # Install the transient-only patch BEFORE start() to avoid a timing race
    # where the real download runs first and finalises the task.
    real_download = orchestrator._operations.download_outputs

    # Wrap to observe whether rmtree would have been called. We patch
    # download_outputs to always return transient errors so rmtree is gated
    # off, and separately record the remote_dir the gateway would clean.
    captured_remote_dir: list[str] = []

    async def transient_only_download(
        session: MachineSession,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: TaskId | None = None,
    ) -> tuple[
        list[tuple[str, Any]],
        list[tuple[str | None, Exception]],
        list[tuple[str | None, Exception]],
    ]:
        captured_remote_dir.append(remote_dir)
        # Transient-only -> gateway must NOT rmtree; remote dir preserved
        return (
            [],
            [(remote_dir + "/1.input.out", SFTPFailure("transient"))],
            [],
        )

    orchestrator._operations.download_outputs = transient_only_download  # type: ignore[method-assign]

    orch_task = asyncio.create_task(orchestrator.start())

    try:
        # Wait a few consume cycles to confirm the task stays RUNNING (deferred).
        # The engine's run.sh sleeps 3s, so the machine is BUSY for ~3s before
        # the consume path can call download_outputs. Wait 8s to guarantee at
        # least one consume cycle ran after the machine transitioned to FREE.
        await asyncio.sleep(8.0)
        async with uow_factory() as uow:
            task = await uow.tasks.get(task_id)
        assert task is not None
        # Task must still be RUNNING (deferred for retry) — NOT terminal DONE
        assert task.status == DomainTaskStatus.RUNNING, (
            f"Expected RUNNING (deferred), got {task.status}"
        )

        # Verify the remote directory still exists on the SSH container.
        # The gateway gated rmtree because transient_errors was non-empty.
        assert captured_remote_dir, "download_outputs was never called"
        remote_dir = captured_remote_dir[-1]
        # Connect and check the remote dir exists
        check_repo = SSHMachineRepository(log=log)
        check_node = Node(
            node_id=NodeId(9999),
            ip=ssh_container["host"],
            ncpus=0,
            enabled=True,
            cloud=None,
            username=ssh_container["username"],
            port=ssh_container["port"],
        )
        check_session = await check_repo.connect(
            node=check_node,
            username=ssh_container["username"],
            client_keys=[ssh_container["key_path"]],
            port=ssh_container["port"],
        )
        try:
            async with check_session.open_sftp() as sftp:
                # The remote dir should still exist (rmtree was gated)
                await sftp.stat(check_session.path(remote_dir))
        finally:
            await check_repo.disconnect(check_session.machine.node_id)
    finally:
        # Restore real download so the orchestrator can finalise the task on
        # shutdown cycle, then stop.
        orchestrator._operations.download_outputs = real_download  # type: ignore[method-assign]
        await _stop_orchestrator(orchestrator, orch_task)
        await _cleanup_node(uow_factory, ssh_container)


async def _stop_orchestrator(
    orchestrator: Orchestrator, orch_task: asyncio.Task[None]
) -> None:
    await orchestrator.stop()
    try:
        await asyncio.wait_for(orch_task, timeout=10)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        orch_task.cancel()


async def _cleanup_node(
    uow_factory: Callable[[], PostgresUnitOfWork],
    ssh_container: dict[str, Any],
) -> None:
    async with uow_factory() as uow:
        all_nodes = await uow.nodes.list_all()
        matching = [n for n in all_nodes if n.ip == ssh_container["host"]]
        if matching:
            await uow.nodes.remove(matching[0].node_id)
        await uow.commit()
