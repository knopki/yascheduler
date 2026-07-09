# FILE: tests/integration/test_task_status_field_check.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for the task_status_field_invariants CHECK constraint on yascheduler_tasks against real PostgreSQL.
#   SCOPE: CHECK rejects forbidden INSERT (TO_DO + allocated_node_id), forbidden UPDATE (RUNNING → allocated_node_id NULL), TO_DO + error, RUNNING + NULL remote_folder; bare DELETE FROM yascheduler_nodes on a node with a RUNNING task is rejected (ON DELETE SET NULL cascade violates the RUNNING row); the hard-remove path (update_status DONE then nodes.remove) succeeds.
#   DEPENDS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-UOW, M-DOMAIN-MODEL
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_check_rejects_todo_with_allocated_node_id - INSERT TO_DO + allocated_node_id raises a CHECK violation referencing task_status_field_invariants
#   test_check_rejects_running_allocated_node_id_null - UPDATE RUNNING SET allocated_node_id = NULL raises a CHECK violation
#   test_check_rejects_todo_with_error - INSERT TO_DO + error raises a CHECK violation
#   test_check_rejects_running_with_null_remote_folder - INSERT RUNNING + allocated_node_id + remote_folder=NULL raises a CHECK violation
#   test_check_rejects_bare_node_delete_with_running_task - DELETE FROM yascheduler_nodes on a node with a RUNNING task is rejected; both rows remain
#   test_hard_remove_path_succeeds_with_running_task - update_status(DONE) then nodes.remove succeeds when the node has a RUNNING task (rows are DONE before the FK cascade fires)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - task-status-field-invariants: initial CHECK-rejection integration tests (forbidden INSERT/UPDATE, TO_DO+error, RUNNING+NULL remote_folder, bare node DELETE rejected, hard-remove path succeeds).
# END_CHANGE_SUMMARY

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


def _insert_node(conn: pg8000.native.Connection, ip: str = "10.0.0.1") -> int:
    """Insert a node and return its node_id (committed)."""
    conn.run(
        "INSERT INTO yascheduler_nodes (ip, enabled) VALUES (:ip, TRUE)",
        ip=ip,
    )
    rows = conn.run("SELECT node_id FROM yascheduler_nodes WHERE ip = :ip", ip=ip)
    return int(rows[0][0])


# START_CONTRACT: test_check_rejects_todo_with_allocated_node_id
#   PURPOSE: Assert the CHECK rejects an INSERT of TO_DO + allocated_node_id (TO_DO requires allocated_node_id IS NULL).
#   INPUTS: { pg_conn: pg8000 connection }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Inserts a node (to satisfy the FK) then a forbidden task row; expects a CHECK violation.
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_check_rejects_todo_with_allocated_node_id
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


# START_CONTRACT: test_check_rejects_running_allocated_node_id_null
#   PURPOSE: Assert the CHECK rejects UPDATE RUNNING SET allocated_node_id = NULL (RUNNING requires allocated_node_id IS NOT NULL).
#   INPUTS: { pg_conn: pg8000 connection }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Inserts a node + a valid RUNNING task; attempts a forbidden UPDATE; expects a CHECK violation.
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_check_rejects_running_allocated_node_id_null
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
            "WHERE status = 'RUNNING'"
        )
    assert _CONSTRAINT in str(excinfo.value), str(excinfo.value)


# START_CONTRACT: test_check_rejects_todo_with_error
#   PURPOSE: Assert the CHECK rejects an INSERT of TO_DO + error (TO_DO requires error IS NULL).
#   INPUTS: { pg_conn: pg8000 connection }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Inserts a forbidden task row; expects a CHECK violation.
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_check_rejects_todo_with_error
async def test_check_rejects_todo_with_error(
    pg_conn: pg8000.native.Connection,
) -> None:
    """INSERT TO_DO + error raises a CHECK violation."""
    with pytest.raises(DatabaseError) as excinfo:
        pg_conn.run(
            "INSERT INTO yascheduler_tasks (status, engine, error) "
            "VALUES ('TO_DO', 'fleur', 'x')"
        )
    assert _CONSTRAINT in str(excinfo.value), str(excinfo.value)


# START_CONTRACT: test_check_rejects_running_with_null_remote_folder
#   PURPOSE: Assert the CHECK rejects an INSERT of RUNNING + allocated_node_id + remote_folder=NULL (RUNNING requires remote_folder IS NOT NULL).
#   INPUTS: { pg_conn: pg8000 connection }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Inserts a node + a forbidden RUNNING task row; expects a CHECK violation.
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_check_rejects_running_with_null_remote_folder
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


# START_CONTRACT: test_check_rejects_bare_node_delete_with_running_task
#   PURPOSE: Assert a bare DELETE FROM yascheduler_nodes on a node with a RUNNING task is rejected by the CHECK (the ON DELETE SET NULL cascade would NULL the RUNNING row's allocated_node_id). Both rows remain after the rejected DELETE.
#   INPUTS: { pg_conn: pg8000 connection }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Inserts a node + a RUNNING task referencing it; attempts a bare node DELETE; expects a CHECK violation; verifies both rows remain.
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_check_rejects_bare_node_delete_with_running_task
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
            "DELETE FROM yascheduler_nodes WHERE node_id = :node_id", node_id=node_id
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
            "WHERE title = 'job'"
        )
    finally:
        pg_conn.run("ROLLBACK")
    assert len(node_row) == 1, "node row must remain after the rejected DELETE"
    assert len(task_row) == 1, "RUNNING task row must remain after the rejected DELETE"
    assert task_row[0][1] == "RUNNING"
    assert task_row[0][2] == node_id


# START_CONTRACT: test_hard_remove_path_succeeds_with_running_task
#   PURPOSE: Assert the hard-remove path (update_status DONE then nodes.remove) succeeds without CHECK violation when the node has a RUNNING task — the rows are DONE before the FK cascade fires.
#   INPUTS: { uow_factory: Callable[[], PostgresUnitOfWork] }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Inserts a node + a RUNNING task; runs update_status(DONE) then nodes.remove(node_id); verifies the node is gone and the task is DONE with allocated_node_id NULL.
#   LINKS: M-PERSISTENCE-UOW, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_hard_remove_path_succeeds_with_running_task
async def test_hard_remove_path_succeeds_with_running_task(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Hard-remove (update_status DONE then nodes.remove) succeeds with a RUNNING task."""
    # Seed a node + a CHECK-valid RUNNING task referencing it.
    async with uow_factory() as uow:
        node = await uow.nodes.insert(NewNode(ip="10.0.0.1", ncpus=2, enabled=True))
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
