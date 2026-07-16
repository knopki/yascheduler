"""Integration tests for the task_status_field_invariants CHECK constraint.

Covers the spec scenarios in
openspec/changes/task-status-field-invariants/specs/db-migrations/spec.md:

* the CHECK rejects a forbidden INSERT (TO_DO + allocated_node_id)
* the CHECK rejects a forbidden UPDATE (RUNNING → allocated_node_id NULL)
* the CHECK rejects TO_DO + error
* the CHECK rejects RUNNING + NULL remote_folder
* a bare DELETE FROM yascheduler_nodes on a node with a RUNNING task is
  rejected (the ON DELETE SET NULL cascade would violate the RUNNING row)
* the hard-remove path (update_status DONE then nodes.remove) succeeds
  because the rows are DONE by the time the FK cascade fires
"""
# region MODULE_CONTRACT
# PURPOSE: Integration tests for the task_status_field_invariants CHECK constraint on yascheduler_tasks against real PostgreSQL.
# SCOPE: CHECK rejects forbidden INSERT (TO_DO + allocated_node_id), forbidden UPDATE (RUNNING → allocated_node_id NULL), TO_DO + error, RUNNING + NULL remote_folder; bare DELETE FROM yascheduler_nodes on a node with a RUNNING task is rejected (ON DELETE SET NULL cascade violates the RUNNING row); the hard-remove path (update_status DONE then nodes.remove) succeeds.
# KEYWORDS: CHECK constraint, task_status_field_invariants, ON DELETE SET NULL
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

import pg8000.native
import pytest
from pg8000 import DatabaseError

from yascheduler.domain.model import (
    NewNode,
    NewTask,
    TaskStatus,
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
    """Hard-remove (update_status DONE then nodes.remove) succeeds with a RUNNING task."""
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

    # The hard-remove flow: flip RUNNING → DONE, then remove the node. The
    # rows are DONE by the time the FK ON DELETE SET NULL cascade fires, so
    # the CHECK (DONE permits NULL allocated_node_id) does not reject.
    async with uow_factory() as uow:
        await uow.tasks.update_status(task_id, TaskStatus.DONE)
        await uow.nodes.remove(node_id)
        await uow.commit()

    # Verify: node gone, task DONE with allocated_node_id NULL.
    async with uow_factory() as uow:
        assert await uow.nodes.get_by_id(node_id) is None
        done = await uow.tasks.get(task_id)
    assert done is not None
    assert done.status == TaskStatus.DONE
    assert done.allocated_node_id is None
