# FILE: tests/e2e/test_full_cycle.py
# VERSION: 2.0.0
# START_MODULE_CONTRACT
#   PURPOSE: E2E test exercising full scheduler lifecycle via real entrypoint code paths across two SSH nodes.
#   SCOPE: Start daemon → submit 4 jobs via _submit_async → assert TO_DO → add 2 nodes via _manage_node_async → poll until DONE → assert outputs, distribution, logs → soft-remove both nodes.
#   DEPENDS: M-ENTRYPOINTS-CLI-SUBMIT, M-ENTRYPOINTS-CLI-MANAGE-NODE, M-APPLICATION-ORCHESTRATOR, M-DI, M-PERSISTENCE-UOW, M-DOMAIN-MODEL, M-APPLICATION-ALLOCATE
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT, M-ENTRYPOINTS-CLI-MANAGE-NODE, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ALLOCATE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_full_cycle - Multi-node entrypoint-driven full lifecycle: 4 jobs across 2 SSH containers
#   _ALLOCATED_MARKER - Structured-log substring emitted by _try_start_on_machine on successful allocation
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - e2e-real-lifecycle: rewrite to drive the full lifecycle through the internal async entrypoints (_submit_async, _manage_node_async) instead of bypassing them with direct repository/UoW calls. Two SSH containers (one shared keypair) exercise multi-node scheduling; four jobs submitted before nodes are added so the allocator's no-provider spin is observable; distribution asserted by set equality + monopoly rejection; soft-remove via _manage_node_async exercised; scheduling activity asserted via in-memory log capture.
#   PREVIOUS_CHANGE: v1.4.0 - fix-static-node-connect-exclusion: drop the `cloud="e2e"` workaround.
#   PREVIOUS_CHANGE: v1.3.0 - session-based-machine-handle section 7.x: Migrate from get_machine_state to get_session.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from yascheduler.domain.model import TaskStatus as DomainTaskStatus
from yascheduler.entrypoints.cli.manage_node import _manage_node_async
from yascheduler.entrypoints.cli.submit import _submit_async
from yascheduler.entrypoints.di import make_daemon

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.entrypoints import Config
    from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

log = logging.getLogger("e2e.test_full_cycle")

_ALLOCATED_MARKER = "[AllocateTask][_try_allocate_to_machine][ALLOCATED]"
_POLL_TIMEOUT_S = 30.0
_POLL_INTERVAL_S = 0.5


async def test_full_cycle(
    e2e_config: Config,
    uow_factory: Callable[[], PostgresUnitOfWork],
    ssh_pool: list[dict[str, Any]],
    log_records: list[logging.LogRecord],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config = e2e_config
    ini_path = _ini_path_from_env()

    ip_a = ssh_pool[0]["host"]
    ip_b = ssh_pool[1]["host"]

    # START_BLOCK_START_DAEMON
    orchestrator = await make_daemon(config)
    orch_task = asyncio.create_task(orchestrator.start())
    # END_BLOCK_START_DAEMON

    task_ids: list[int] = []
    try:
        # START_BLOCK_SUBMIT_JOBS
        task_ids = await _submit_four_jobs(
            config, ini_path, monkeypatch, tmp_path, capfd
        )
        # END_BLOCK_SUBMIT_JOBS

        # START_BLOCK_ASSERT_QUEUED
        await _assert_all_status(
            uow_factory, task_ids, DomainTaskStatus.TO_DO, "after submit, before nodes"
        )
        # END_BLOCK_ASSERT_QUEUED

        # START_BLOCK_ADD_NODES
        await _add_nodes(ssh_pool, ini_path)
        await _assert_nodes_present(uow_factory, {ip_a, ip_b})
        # END_BLOCK_ADD_NODES

        # START_BLOCK_WAIT_COMPLETION
        seen_running = await _wait_all_done(uow_factory, task_ids)
        # Assert every task passed through RUNNING (lifecycle: TO_DO -> RUNNING -> DONE).
        # The test_shell engine sleeps 3s, so each task is RUNNING for >=3s;
        # the 0.5s poll interval guarantees every RUNNING window is observed.
        missing_running = set(task_ids) - set(seen_running)
        assert not missing_running, (
            f"tasks {missing_running} were never observed RUNNING; "
            f"seen_running={seen_running}"
        )
        # Every observed RUNNING task must have been allocated to one of the pool IPs.
        assert set(seen_running.values()).issubset({ip_a, ip_b}), (
            f"RUNNING allocated_ips={set(seen_running.values())} "
            f"not subset of {{{ip_a}, {ip_b}}}"
        )
        # END_BLOCK_WAIT_COMPLETION

        # START_BLOCK_VERIFY_OUTPUTS
        tasks = await _read_tasks(uow_factory, task_ids)
        assert len(task_ids) == len(tasks), (
            f"length mismatch: task_ids={len(task_ids)} tasks={len(tasks)}"
        )
        for tid, task in zip(task_ids, tasks):
            assert task is not None, f"task {tid} vanished from DB"
            assert task.status == DomainTaskStatus.DONE, (
                f"task {tid} status={task.status}, expected DONE"
            )
            assert task.context.error is None, (
                f"task {tid} error={task.context.error!r}"
            )
            local_folder = task.context.local_folder
            assert local_folder, f"task {tid} missing local_folder"
            n = task_ids.index(tid) + 1
            expected = f"hello e2e {n}"
            out_file = Path(str(local_folder)) / "1.input.out"
            assert out_file.exists(), f"task {tid} output missing: {out_file}"
            assert out_file.read_text() == expected, (
                f"task {tid} output={out_file.read_text()!r}, expected {expected!r}"
            )
        # END_BLOCK_VERIFY_OUTPUTS

        # START_BLOCK_ASSERT_DISTRIBUTION
        ips = {t.allocated_ip for t in tasks if t is not None}
        assert ips == {ip_a, ip_b}, (
            f"expected both nodes used, got allocated_ips={ips}; "
            f"expected {{{ip_a}, {ip_b}}}"
        )
        for ip in (ip_a, ip_b):
            count = sum(1 for t in tasks if t is not None and t.allocated_ip == ip)
            assert count < len(task_ids), (
                f"node {ip} received all {len(task_ids)} tasks — monopoly rejected"
            )
        # END_BLOCK_ASSERT_DISTRIBUTION

        # START_BLOCK_ASSERT_LOGS
        _assert_allocation_logs(log_records, task_ids, {ip_a, ip_b})
        # END_BLOCK_ASSERT_LOGS

        # START_BLOCK_SOFT_REMOVE_NODES
        await _remove_nodes_soft(ssh_pool, ini_path)
        await _assert_nodes_present(uow_factory, set())
        # END_BLOCK_SOFT_REMOVE_NODES

    finally:
        # START_BLOCK_STOP_DAEMON
        await orchestrator.stop()
        try:
            await asyncio.wait_for(orch_task, timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            orch_task.cancel()
        # END_BLOCK_STOP_DAEMON


# START_CONTRACT: _ini_path_from_env
#   PURPOSE: Read the INI path the session-scoped e2e_config fixture published via YASCHEDULER_CONF_PATH.
#   INPUTS: { None }
#   OUTPUTS: { str - absolute INI path set by conftest.e2e_config }
#   SIDE_EFFECTS: None
#   RAISES: RuntimeError - if the env var is unset (fixture ordering bug)
#   LINKS: e2e_config fixture (tests/e2e/conftest.py)
# END_CONTRACT: _ini_path_from_env
def _ini_path_from_env() -> str:
    path = os.environ.get("YASCHEDULER_CONF_PATH")
    if not path:
        raise RuntimeError(
            "YASCHEDULER_CONF_PATH unset; e2e_config fixture must run first"
        )
    return path


# START_CONTRACT: _submit_four_jobs
#   PURPOSE: Submit four tasks via _submit_async, one per temp CWD holding a distinct 1.input payload; capture each task_id from stdout.
#   INPUTS: {
#     config: Config - parsed e2e config (unused directly, kept for future engine introspection),
#     ini_path: str - INI path to pass as --config,
#     monkeypatch: pytest.MonkeyPatch - per-call chdir isolation,
#     tmp_path: Path - base temp dir for per-job CWDs,
#     capfd: pytest.CaptureFixture - captures _submit_async's print(str(task_id))
#   }
#   OUTPUTS: { list[int] - four positive task_ids in submission order }
#   SIDE_EFFECTS: Creates per-job temp CWDs with 1.input; chdir's into each during _submit_async; writes per-job script files.
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT
# END_CONTRACT: _submit_four_jobs
async def _submit_four_jobs(
    config: Config,
    ini_path: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> list[int]:
    del config  # config is validated via _submit_async's own parse_config
    task_ids: list[int] = []
    for n in range(1, 5):
        job_dir = tmp_path / f"job_{n}"
        job_dir.mkdir(parents=True)
        (job_dir / "1.input").write_text(f"hello e2e {n}")

        script = tmp_path / f"submit_{n}.script"
        script.write_text(f"ENGINE=test_shell\nLABEL=job_{n}\n")

        monkeypatch.chdir(job_dir)
        capfd.readouterr()
        await _submit_async([str(script), "--config", ini_path])
        out = capfd.readouterr().out.strip()
        monkeypatch.undo()

        assert out, f"job {n}: _submit_async printed nothing to stdout"
        task_id = int(out)
        assert task_id > 0, f"job {n}: task_id={task_id} not positive"
        task_ids.append(task_id)
    return task_ids


# START_CONTRACT: _assert_all_status
#   PURPOSE: Read all tasks by id and assert each has the expected status, with a context label for failure messages.
#   INPUTS: {
#     uow_factory: Callable[[], PostgresUnitOfWork],
#     task_ids: list[int],
#     expected: DomainTaskStatus,
#     label: str - human context for the assertion
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None — read-only UoW.
#   LINKS: M-PERSISTENCE-UOW
# END_CONTRACT: _assert_all_status
async def _assert_all_status(
    uow_factory: Callable[[], PostgresUnitOfWork],
    task_ids: list[int],
    expected: DomainTaskStatus,
    label: str,
) -> None:
    async with uow_factory() as uow:
        for tid in task_ids:
            task = await uow.tasks.get(tid)
            assert task is not None, f"task {tid} missing ({label})"
            assert task.status == expected, (
                f"task {tid} status={task.status}, expected {expected} ({label})"
            )


# START_CONTRACT: _add_nodes
#   PURPOSE: Add both ssh_pool nodes via _manage_node_async([host:port, --config, ini]), exercising the real _add_node path.
#   INPUTS: { ssh_pool: list[dict] - two entries (host=bridge IP, port=2222), ini_path: str }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Per entry: SSH connect + setup_node + uow.nodes.add + commit + disconnect.
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_CONTRACT: _add_nodes
async def _add_nodes(ssh_pool: list[dict[str, Any]], ini_path: str) -> None:
    for entry in ssh_pool:
        await _manage_node_async([_host_spec(entry), "--config", ini_path])


# START_CONTRACT: _assert_nodes_present
#   PURPOSE: Assert the DB node row IPs exactly match the expected set.
#   INPUTS: { uow_factory, expected_ips: set[str] - empty set asserts no nodes }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None — read-only UoW.
#   LINKS: M-PERSISTENCE-UOW
# END_CONTRACT: _assert_nodes_present
async def _assert_nodes_present(
    uow_factory: Callable[[], PostgresUnitOfWork],
    expected_ips: set[str],
) -> None:
    async with uow_factory() as uow:
        nodes = await uow.nodes.list_all()
    actual = {n.ip for n in nodes}
    assert actual == expected_ips, f"node IPs={actual}, expected={expected_ips}"


# START_CONTRACT: _wait_all_done
#   PURPOSE: Poll the DB until all task_ids reach DONE or the timeout elapses; collect RUNNING snapshots; fail the test on timeout.
#   INPUTS: { uow_factory, task_ids: list[int] }
#   OUTPUTS: { dict[int, str] - task_id -> allocated_ip for every task observed RUNNING }
#   SIDE_EFFECTS: None — read-only polls.
#   LINKS: M-PERSISTENCE-UOW
# END_CONTRACT: _wait_all_done
async def _wait_all_done(
    uow_factory: Callable[[], PostgresUnitOfWork],
    task_ids: list[int],
) -> dict[int, str]:
    deadline = asyncio.get_running_loop().time() + _POLL_TIMEOUT_S
    statuses: list[Any] = []
    seen_running: dict[int, str] = {}
    while asyncio.get_running_loop().time() < deadline:
        async with uow_factory() as uow:
            statuses = []
            for tid in task_ids:
                t = await uow.tasks.get(tid)
                statuses.append(t.status if t else None)
                if t and t.status == DomainTaskStatus.RUNNING and t.allocated_ip:
                    seen_running[tid] = t.allocated_ip
        if all(s == DomainTaskStatus.DONE for s in statuses):
            return seen_running
        await asyncio.sleep(_POLL_INTERVAL_S)
    pytest.fail(
        f"tasks not all DONE within {_POLL_TIMEOUT_S}s; "
        f"task_ids={task_ids} last statuses={statuses}"
    )


# START_CONTRACT: _read_tasks
#   PURPOSE: Read all tasks by id in a single UoW, returning the list (may contain None if a row vanished).
#   INPUTS: { uow_factory, task_ids: list[int] }
#   OUTPUTS: { list[Task | None] - parallel to task_ids }
#   SIDE_EFFECTS: None — read-only UoW.
#   LINKS: M-PERSISTENCE-UOW
# END_CONTRACT: _read_tasks
async def _read_tasks(
    uow_factory: Callable[[], PostgresUnitOfWork],
    task_ids: list[int],
) -> list[Any]:
    async with uow_factory() as uow:
        tasks: list[Any] = [await uow.tasks.get(tid) for tid in task_ids]
    return tasks


# START_CONTRACT: _assert_allocation_logs
#   PURPOSE: Assert one [ALLOCATED] log record per task_id and that both node IPs appear among the logged ip= values.
#   INPUTS: { records: list[LogRecord], task_ids: set[int] (coerced from list), expected_ips: set[str] }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None — pure assertion over captured records.
#   LINKS: M-APPLICATION-ALLOCATE
# END_CONTRACT: _assert_allocation_logs
def _assert_allocation_logs(
    records: list[logging.LogRecord],
    task_ids: list[int],
    expected_ips: set[str],
) -> None:
    allocated_msgs = [
        r.getMessage() for r in records if _ALLOCATED_MARKER in r.getMessage()
    ]
    # One ALLOCATED record per task_id. The message format is
    # "[AllocateTask][_try_allocate_to_machine][ALLOCATED] task_id=%s ip=%s".
    seen_task_ids: set[int] = set()
    seen_ips: set[str] = set()
    # Word-boundary matching: `task_id=3\b` avoids matching inside `task_id=30`;
    # `ip=10.88.0.1\b` avoids matching inside `ip=10.88.0.165`. Task IDs
    # accumulate across sessions (TRUNCATE without RESTART IDENTITY), so naive
    # substring matching would eventually false-positive.
    for msg in allocated_msgs:
        for tid in task_ids:
            if re.search(rf"task_id={tid}\b", msg):
                seen_task_ids.add(tid)
        for ip in expected_ips:
            if re.search(rf"ip={re.escape(ip)}\b", msg):
                seen_ips.add(ip)
    missing_task_ids = set(task_ids) - seen_task_ids
    assert not missing_task_ids, (
        f"no [ALLOCATED] log for task_ids={missing_task_ids}; "
        f"captured ALLOCATED msgs={allocated_msgs}"
    )
    missing_ips = expected_ips - seen_ips
    assert not missing_ips, (
        f"[ALLOCATED] logs never mention ip={missing_ips}; "
        f"captured ALLOCATED msgs={allocated_msgs}"
    )


# START_CONTRACT: _remove_nodes_soft
#   PURPOSE: Soft-remove both ssh_pool nodes via _manage_node_async([host:port, --remove-soft, --config, ini]).
#   INPUTS: { ssh_pool: list[dict], ini_path: str }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Per entry: _remove_node_soft queries RUNNING tasks for the ip (empty in the happy path) and removes the node row.
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_CONTRACT: _remove_nodes_soft
async def _remove_nodes_soft(
    ssh_pool: list[dict[str, Any]],
    ini_path: str,
) -> None:
    for entry in ssh_pool:
        await _manage_node_async(
            [_host_spec(entry), "--remove-soft", "--config", ini_path]
        )


# START_CONTRACT: _host_spec
#   PURPOSE: Render an ssh_pool entry as the yasetnode positional [user@]host[:port] grammar.
#   INPUTS: { entry: dict - has 'host', 'port', 'username' }
#   OUTPUTS: { str - e.g. "10.88.0.165:2222" (port always included; username inherited from INI [remote]) }
#   SIDE_EFFECTS: None
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_CONTRACT: _host_spec
def _host_spec(entry: dict[str, Any]) -> str:
    # Username is inherited from [remote] in the INI; omit it from the spec so
    # _add_node resolves spec.username from config.remote.username.
    return f"{entry['host']}:{entry['port']}"
