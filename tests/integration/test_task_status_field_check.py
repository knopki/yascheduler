"""Integration tests for the task_status_field_invariants CHECK constraint.

Covers the spec scenarios in
openspec/changes/task-status-field-invariants/specs/db-migrations/spec.md:

* the CHECK rejects a forbidden INSERT (TO_DO + allocated_node_id)
* the CHECK rejects a forbidden UPDATE (RUNNING → allocated_node_id NULL)
* the CHECK rejects TO_DO + error
* the CHECK rejects RUNNING + NULL remote_folder
* a bare DELETE FROM yascheduler_nodes on a node with a RUNNING task is
  rejected (the ON DELETE SET NULL cascade would violate the RUNNING row)
* the hard-remove path (load → abandon → save then nodes.remove) succeeds
  because the rows are DONE (with TaskAbandoned emitted) by the time the
  FK cascade fires
"""
# region MODULE_CONTRACT
# PURPOSE: Integration tests for the task_status_field_invariants CHECK constraint on yascheduler_tasks against real PostgreSQL.
# SCOPE: CHECK rejects forbidden INSERT (TO_DO + allocated_node_id), forbidden UPDATE (RUNNING → allocated_node_id NULL), TO_DO + error, RUNNING + NULL remote_folder; bare DELETE FROM yascheduler_nodes on a node with a RUNNING task is rejected (ON DELETE SET NULL cascade violates the RUNNING row); the hard-remove path (load → abandon → save then nodes.remove) succeeds and emits TaskAbandoned for each cleaned-up task.
# KEYWORDS: CHECK constraint, task_status_field_invariants, ON DELETE SET NULL, TaskAbandoned
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

import pg8000.native
import pytest
from pg8000 import DatabaseError

from yascheduler.domain.events import TaskAbandoned
from yascheduler.domain.model import (
    Done,
    NewNode,
    NewTask,
    TaskStatus,
    allocated_node_id_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

pytestmark = pytest.mark.integration

_CONSTRAINT = "task_status_field_invariants"


def _insert_node(conn: pg8000.native.Connection, hostname: str = "10.0.0.1") -> int:
    """Insert a node and return its node_id (committed)."""
    conn.run(
        "INSERT INTO yascheduler_nodes (hostname, enabled) VALUES (:hostname, TRUE)",
        hostname=hostname,
    )
    rows = conn.run(
        "SELECT node_id FROM yascheduler_nodes WHERE hostname = :hostname",
        hostname=hostname,
    )
    return int(rows[0][0])


async def test_check_rejects_todo_with_allocated_node_id(
    pg_conn: pg8000.native.Connection,
) -> None:
    """INSERT TO_DO + allocated_node_id raises a CHECK violation."""
    node_id = _insert_node(pg_conn)
    with pytest.raises(DatabaseError) as excinfo:
        pg_conn.run(
            "INSERT INTO yascheduler_tasks (status, engine, allocated_node_id) "
            "VALUES ('TO_DO', 'fleur', :node_id)",
            node_id=node_id,
        )
    assert _CONSTRAINT in str(excinfo.value), str(excinfo.value)


async def test_check_rejects_running_allocated_node_id_null(
    pg_conn: pg8000.native.Connection,
) -> None:
    """UPDATE RUNNING SET allocated_node_id = NULL raises a CHECK violation."""
    node_id = _insert_node(pg_conn)
    pg_conn.run(
        "INSERT INTO yascheduler_tasks (title, status, engine, allocated_node_id, remote_folder) "
        "VALUES ('job', 'RUNNING', 'fleur', :node_id, '/remote/job')",
        node_id=node_id,
    )
    with pytest.raises(DatabaseError) as excinfo:
        pg_conn.run(
            "UPDATE yascheduler_tasks SET allocated_node_id = NULL "
            "WHERE status = 'RUNNING'",
        )
    assert _CONSTRAINT in str(excinfo.value), str(excinfo.value)


async def test_check_rejects_todo_with_error(
    pg_conn: pg8000.native.Connection,
) -> None:
    """INSERT TO_DO + error raises a CHECK violation."""
    with pytest.raises(DatabaseError) as excinfo:
        pg_conn.run(
            "INSERT INTO yascheduler_tasks (status, engine, error) "
            "VALUES ('TO_DO', 'fleur', 'x')",
        )
    assert _CONSTRAINT in str(excinfo.value), str(excinfo.value)


async def test_check_rejects_running_with_null_remote_folder(
    pg_conn: pg8000.native.Connection,
) -> None:
    """INSERT RUNNING + allocated_node_id + remote_folder=NULL raises a CHECK violation."""
    node_id = _insert_node(pg_conn)
    with pytest.raises(DatabaseError) as excinfo:
        pg_conn.run(
            "INSERT INTO yascheduler_tasks (title, status, engine, allocated_node_id, remote_folder) "
            "VALUES ('job', 'RUNNING', 'fleur', :node_id, NULL)",
            node_id=node_id,
        )
    assert _CONSTRAINT in str(excinfo.value), str(excinfo.value)


async def test_check_rejects_bare_node_delete_with_running_task(
    pg_conn: pg8000.native.Connection,
) -> None:
    """Bare DELETE FROM yascheduler_nodes with a RUNNING task is rejected; both rows remain."""
    node_id = _insert_node(pg_conn)
    pg_conn.run(
        "INSERT INTO yascheduler_tasks (title, status, engine, allocated_node_id, remote_folder) "
        "VALUES ('job', 'RUNNING', 'fleur', :node_id, '/remote/job')",
        node_id=node_id,
    )
    with pytest.raises(DatabaseError) as excinfo:
        pg_conn.run(
            "DELETE FROM yascheduler_nodes WHERE node_id = :node_id",
            node_id=node_id,
        )
    assert _CONSTRAINT in str(excinfo.value), str(excinfo.value)

    # Both rows must still be present after the rejected DELETE.
    pg_conn.run("BEGIN")
    try:
        node_row = pg_conn.run(
            "SELECT node_id FROM yascheduler_nodes WHERE node_id = :node_id",
            node_id=node_id,
        )
        task_row = pg_conn.run(
            "SELECT task_id, status, allocated_node_id FROM yascheduler_tasks "
            "WHERE title = 'job'",
        )
    finally:
        pg_conn.run("ROLLBACK")
    assert len(node_row) == 1, "node row must remain after the rejected DELETE"
    assert len(task_row) == 1, "RUNNING task row must remain after the rejected DELETE"
    assert task_row[0][1] == "RUNNING"
    assert task_row[0][2] == node_id


async def test_hard_remove_path_succeeds_with_running_task(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Hard-remove (load → abandon → save then nodes.remove) succeeds with a RUNNING task and emits TaskAbandoned."""
    # Seed a node + a CHECK-valid RUNNING task referencing it.
    async with uow_factory() as uow:
        node = await uow.nodes.insert(
            NewNode(hostname="10.0.0.1", ncpus=2, enabled=True),
        )
        task = await uow.tasks.insert(NewTask(label="job", engine="fleur"))
        task = task.run(node.node_id, "/r")
        await uow.tasks.save(task)
        await uow.commit()
        node_id = node.node_id
        task_id = task.task_id

    # The hard-remove flow: load each RUNNING task, apply abandon() (RUNNING →
    # DONE with TaskAbandoned), save, then remove the node. The rows are DONE
    # by the time the FK ON DELETE SET NULL cascade fires, so the CHECK (DONE
    # permits NULL allocated_node_id) does not reject.
    async with uow_factory() as uow:
        task = await uow.tasks.get_running(task_id)
        assert task is not None
        abandoned = task.abandon()
        # TaskAbandoned is now emitted unconditionally — webhook-dispatchable
        # for the cleaned-up task (behavior change vs the old update_status
        # flip, which wrote no event).
        assert any(isinstance(evt, TaskAbandoned) for evt in abandoned.events)
        await uow.tasks.save(abandoned)
        await uow.nodes.remove(node_id)
        await uow.commit()

    # Verify: node gone, task DONE with allocated_node_id NULL (cascade).
    async with uow_factory() as uow:
        assert await uow.nodes.get_by_id(node_id) is None
        done = await uow.tasks.get(task_id)
    assert done is not None
    assert done.status == TaskStatus.DONE
    assert allocated_node_id_of(done) is None
    assert isinstance(done.state, Done)
    assert done.state.error == "node is gone"


async def test_hard_remove_skips_task_that_raced_to_done(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """A task that transitions to DONE between the id-list read and get_running is skipped (None), not raised.

    Mirrors the _remove_node_hard race window: list_ids_by_node_id_and_status
    returns a RUNNING task_id, but by the time get_running loads it the row has
    moved to DONE. get_running returns None (absent OR wrong status), so the
    loop skips it without raising and without abandoning.
    """
    # Seed a node + a CHECK-valid RUNNING task referencing it.
    async with uow_factory() as uow:
        node = await uow.nodes.insert(
            NewNode(hostname="10.0.0.2", ncpus=2, enabled=True),
        )
        task = await uow.tasks.insert(NewTask(label="race", engine="fleur"))
        task = task.run(node.node_id, "/r")
        await uow.tasks.save(task)
        await uow.commit()
        node_id = node.node_id
        task_id = task.task_id

    # Step 1 of _remove_node_hard: read the RUNNING id list.
    async with uow_factory() as uow:
        task_ids = await uow.tasks.list_ids_by_node_id_and_status(
            node_id,
            TaskStatus.RUNNING,
        )
    assert task_id in task_ids

    # Race: the task completes (RUNNING -> DONE) between the id-list read and
    # the get_running load — e.g. the consume loop finalised it.
    async with uow_factory() as uow:
        running = await uow.tasks.get_running(task_id)
        assert running is not None
        await uow.tasks.save(
            running.complete(local_folder="/l", remote_folder="/r"),
        )
        await uow.commit()

    # Step 2 of _remove_node_hard: get_running now returns None (wrong status).
    # The hard-remove loop's `if task is not None` skips it — no raise, no
    # abandon. This is the None-skip that replaced the isinstance race guard.
    async with uow_factory() as uow:
        raced = await uow.tasks.get_running(task_id)
    assert raced is None

    # The task stays DONE (the racer's completion wins); it was not abandoned.
    async with uow_factory() as uow:
        done = await uow.tasks.get(task_id)
    assert done is not None
    assert done.status == TaskStatus.DONE
    assert isinstance(done.state, Done)
    assert done.state.error is None
