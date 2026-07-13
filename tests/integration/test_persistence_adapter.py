# FILE: tests/integration/test_persistence_adapter.py
# VERSION: 1.5.0
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for persistence adapter against real PostgreSQL via testcontainers.
#   SCOPE: PostgresTaskRepository CRUD, PostgresNodeRepository CRUD, PostgresUnitOfWork commit/rollback.
#   DEPENDS: M-PERSISTENCE-POSTGRES, M-PERSISTENCE-UOW, M-INFRA-DB-CONFIG
#   LINKS: M-PERSISTENCE-POSTGRES, M-PERSISTENCE-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_repo_task_insert_and_get - round-trip insert + get with typed fields and JSONB extra
#   test_repo_task_get_none - get() returns None for non-existent task
#   test_repo_task_save_updates - save() updates existing task fields via update_by_id
#   test_repo_task_list_by_status - list_by_status filtering
#   test_repo_task_count_by_status - count_by_status aggregates
#   test_repo_task_update_status_atomic - update_status only changes status
#   test_repo_node_crud - full node lifecycle: add, get, enable, disable, remove
#   test_repo_node_list_filters - list_enabled / list_disabled subsets
#   test_repo_node_update - update persists all mutable node fields
#   test_repo_node_tmp_via_insert - insert(NewNode(cloud=..., enabled=False)) inserts a tmp row carrying ip="" and node_id
#   test_repo_node_count - count_by_cloud and count_by_status aggregates
#   test_repo_node_get_by_ips - batch get_by_ips returns matching nodes
#   test_repo_node_get_by_id - get_by_id lookup by primary key
#   test_repo_node_list_all_ordered_by_node_id - list_all ordering by node_id
#   test_uow_integration - UoW creates repos, commit persists, exit closes
#   test_uow_rollback_integration - rollback discards uncommitted changes on exception
#   test_repo_task_insert_returns_created_updated_at - insert returns Task with created_at/updated_at set
#   test_repo_task_save_triggers_updated_at - save (UPDATE) triggers updated_at to advance
#   test_repo_task_list_by_status_enum_cast - list_by_status with cast(:statuses AS task_status[]) works
#   test_repo_task_count_by_status_name_lookup - count_by_status returns keys via name lookup
#   test_repo_task_list_ids_by_node_id_and_status - list_ids_by_node_id_and_status filters correctly
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - refactor-task-state-transitions: replace allocate_to/mark_running/with_remote_folder chains with task.run(node_id, remote_folder); replace with_remote_folder with replace for test-only fixture construction.
#   PREVIOUS_CHANGE: v1.5.0 - drop-task-context-entity: Task/NewTask constructed with flat typed fields (no TaskContext); context.X reads → task.X; TaskContext import removed.
# END_CHANGE_SUMMARY

"""Integration tests for persistence adapter repositories and Unit of Work."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pg8000.native
import pytest

from yascheduler.application.message_bus import MessageBus
from yascheduler.domain.model import (
    NewNode,
    NewTask,
    Node,
    NodeId,
    TaskId,
)
from yascheduler.domain.model import (
    TaskStatus as DomainTaskStatus,
)
from yascheduler.infra.persistence import PostgresDbConfig
from yascheduler.infra.persistence.postgres import (
    PostgresNodeRepository,
    PostgresTaskRepository,
)
from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

# ====================================================================
# Task 8.2: PostgresTaskRepository CRUD
# ====================================================================


# START_CONTRACT: test_repo_task_insert_and_get
#   PURPOSE: Verify round-trip insert -> get with all typed fields including JSONB extra roundtrip.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.insert, PostgresTaskRepository.get
# END_CONTRACT: test_repo_task_insert_and_get
async def test_repo_task_insert_and_get(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """Insert a task via repo, get it back, verify all fields including JSONB roundtrip."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)

    new_task = NewTask(
        label="test-task",
        engine="fleur",
        local_folder="/l",
        webhook_url="https://hook.example.com",
        extra={"param": 42},
    )
    inserted = await repo.insert(new_task)
    assert inserted.task_id.value >= 1
    assert inserted.label == "test-task"
    assert inserted.status == DomainTaskStatus.TO_DO
    assert inserted.engine == "fleur"
    assert inserted.local_folder == "/l"
    assert inserted.webhook_url == "https://hook.example.com"
    assert inserted.extra["param"] == 42
    assert inserted.webhook_custom_params == {}
    assert inserted.remote_folder is None

    # Set remote_folder post-insert to verify round-trip
    inserted = replace(inserted, remote_folder="/r")
    await repo.save(inserted)

    # Retrieve by ID
    retrieved = await repo.get(inserted.task_id)
    assert retrieved is not None
    assert retrieved.task_id == inserted.task_id
    assert retrieved.label == inserted.label
    assert retrieved.engine == "fleur"
    assert retrieved.remote_folder == "/r"
    assert retrieved.extra["param"] == 42


# START_CONTRACT: test_repo_task_get_none
#   PURPOSE: Verify get() returns None for non-existent task.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.get
# END_CONTRACT: test_repo_task_get_none
async def test_repo_task_get_none(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """get() returns None for non-existent task."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    assert await repo.get(TaskId(99999)) is None


# START_CONTRACT: test_repo_task_save_updates
#   PURPOSE: Verify save() updates an existing task's fields via update_by_id.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.save, PostgresTaskRepository.get
# END_CONTRACT: test_repo_task_save_updates
async def test_repo_task_save_updates(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """Save updates an existing task's fields via update_by_id."""
    task_repo = PostgresTaskRepository(pg_conn, pg_executor)
    node_repo = PostgresNodeRepository(pg_conn, pg_executor)
    task = await task_repo.insert(NewTask(label="initial", engine="fleur"))
    node = await node_repo.insert(NewNode(hostname="10.0.0.1", ncpus=2, enabled=True))

    # Build a CHECK-valid RUNNING task via task.run.
    # A bare Task(status=RUNNING) with NULL allocated_node_id/remote_folder is
    # rejected by the task_status_field_invariants CHECK.
    updated = task.run(node.node_id, "/r")
    updated = replace(updated, label="renamed")
    await task_repo.save(updated)

    retrieved = await task_repo.get(task.task_id)
    assert retrieved is not None
    assert retrieved.label == "renamed"
    assert retrieved.status == DomainTaskStatus.RUNNING


# START_CONTRACT: test_repo_task_list_by_status
#   PURPOSE: Verify list_by_status returns only tasks with the given statuses.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.list_by_status
# END_CONTRACT: test_repo_task_list_by_status
async def test_repo_task_list_by_status(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """list_by_status filters correctly."""
    task_repo = PostgresTaskRepository(pg_conn, pg_executor)
    node_repo = PostgresNodeRepository(pg_conn, pg_executor)
    t1 = await task_repo.insert(NewTask(label="todo", engine="fleur"))
    node = await node_repo.insert(NewNode(hostname="10.0.0.1", ncpus=2, enabled=True))
    t2 = await task_repo.insert(NewTask(label="running", engine="fleur"))
    # CHECK-valid RUNNING via task.run.
    t2 = t2.run(node.node_id, "/r")
    await task_repo.save(t2)
    t2_id = t2.task_id

    todos = await task_repo.list_by_status({DomainTaskStatus.TO_DO})
    assert len(todos) == 1
    assert todos[0].task_id == t1.task_id

    running = await task_repo.list_by_status({DomainTaskStatus.RUNNING})
    assert len(running) == 1
    assert running[0].task_id == t2_id


# START_CONTRACT: test_repo_task_count_by_status
#   PURPOSE: Verify count_by_status returns correct aggregates.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.count_by_status
# END_CONTRACT: test_repo_task_count_by_status
async def test_repo_task_count_by_status(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """count_by_status returns correct aggregates."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    await repo.insert(NewTask(label="t1", engine="fleur"))
    await repo.insert(NewTask(label="t2", engine="fleur"))
    t3 = await repo.insert(NewTask(label="t3", engine="fleur"))
    await repo.update_status(t3.task_id, DomainTaskStatus.DONE)

    counts = await repo.count_by_status()
    assert counts.get(DomainTaskStatus.TO_DO) == 2
    assert counts.get(DomainTaskStatus.DONE) == 1


# START_CONTRACT: test_repo_task_update_status_atomic
#   PURPOSE: Verify update_status only changes status, preserving other fields.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.update_status
# END_CONTRACT: test_repo_task_update_status_atomic
async def test_repo_task_update_status_atomic(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """update_status only changes the status field."""
    task_repo = PostgresTaskRepository(pg_conn, pg_executor)
    node_repo = PostgresNodeRepository(pg_conn, pg_executor)
    node = await node_repo.insert(NewNode(hostname="10.0.0.1", ncpus=2, enabled=True))
    task = await task_repo.insert(NewTask(label="keep-label", engine="fleur"))
    # Seed a CHECK-valid RUNNING row (allocated_node_id + remote_folder set)
    # so the subsequent update_status to DONE is CHECK-valid (DONE is
    # unconstrained). A bare update_status(TO_DO → RUNNING) would be rejected
    # because RUNNING requires allocated_node_id + remote_folder.
    task = task.run(node.node_id, "/r")
    await task_repo.save(task)

    await task_repo.update_status(task.task_id, DomainTaskStatus.DONE)
    retrieved = await task_repo.get(task.task_id)
    assert retrieved is not None
    assert retrieved.status == DomainTaskStatus.DONE
    assert retrieved.label == "keep-label"


# START_CONTRACT: test_repo_task_insert_returns_created_updated_at
#   PURPOSE: Verify insert returns a Task with created_at and updated_at set.
#   INPUTS: { pg_conn, pg_executor }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.insert
# END_CONTRACT: test_repo_task_insert_returns_created_updated_at
async def test_repo_task_insert_returns_created_updated_at(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """Insert returns Task with created_at and updated_at populated."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    task = await repo.insert(NewTask(label="ts-test", engine="fleur"))
    assert task.created_at is not None
    assert task.updated_at is not None
    assert task.created_at <= task.updated_at


# START_CONTRACT: test_repo_task_save_triggers_updated_at
#   PURPOSE: Verify save (UPDATE) triggers the touch trigger, advancing updated_at while preserving created_at.
#   INPUTS: { pg_conn, pg_executor }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.insert, PostgresTaskRepository.save
# END_CONTRACT: test_repo_task_save_triggers_updated_at
async def test_repo_task_save_triggers_updated_at(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """Save (UPDATE) triggers updated_at to advance; created_at unchanged."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    task = await repo.insert(NewTask(label="touch-test", engine="fleur"))
    assert task.created_at is not None
    assert task.updated_at is not None
    created_before = task.created_at
    updated_before = task.updated_at

    # Perform an update via save — re-save as a CHECK-valid TO_DO row with a
    # changed label (the trigger fires on any UPDATE; the status value is
    # incidental to this test). A bare Task(status=RUNNING) with NULL
    # allocated_node_id/remote_folder is rejected by task_status_field_invariants.
    updated = replace(task, label="touch-test-renamed")
    await repo.save(updated)

    retrieved = await repo.get(task.task_id)
    assert retrieved is not None
    assert retrieved.created_at == created_before
    assert retrieved.updated_at is not None
    assert retrieved.updated_at > updated_before


# START_CONTRACT: test_repo_task_list_by_status_enum_cast
#   PURPOSE: Verify list_by_status with cast(:statuses AS task_status[]) works.
#   INPUTS: { pg_conn, pg_executor }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.list_by_status
# END_CONTRACT: test_repo_task_list_by_status_enum_cast
async def test_repo_task_list_by_status_enum_cast(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """list_by_status with enum-label cast works."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    t1 = await repo.insert(NewTask(label="enum-todo", engine="fleur"))
    t2 = await repo.insert(NewTask(label="enum-done", engine="fleur"))
    await repo.update_status(t2.task_id, DomainTaskStatus.DONE)

    todos = await repo.list_by_status({DomainTaskStatus.TO_DO})
    assert len(todos) == 1
    assert todos[0].task_id == t1.task_id


# START_CONTRACT: test_repo_task_count_by_status_name_lookup
#   PURPOSE: Verify count_by_status returns keys via TaskStatus name lookup.
#   INPUTS: { pg_conn, pg_executor }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.count_by_status
# END_CONTRACT: test_repo_task_count_by_status_name_lookup
async def test_repo_task_count_by_status_name_lookup(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """count_by_status keys are TaskStatus members accessible via name lookup."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    await repo.insert(NewTask(label="n1", engine="fleur"))
    await repo.insert(NewTask(label="n2", engine="fleur"))
    t3 = await repo.insert(NewTask(label="n3", engine="fleur"))
    await repo.update_status(t3.task_id, DomainTaskStatus.DONE)

    counts = await repo.count_by_status()
    # Keys are TaskStatus enum members, accessible by name
    assert counts[DomainTaskStatus.TO_DO] == 2
    assert counts[DomainTaskStatus.DONE] == 1


# START_CONTRACT: test_repo_task_list_ids_by_node_id_and_status
#   PURPOSE: Verify list_ids_by_node_id_and_status filters by allocated_node_id and status.
#   INPUTS: { pg_conn, pg_executor }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Inserts a node + tasks with allocated_node_id
#   LINKS: PostgresTaskRepository.list_ids_by_node_id_and_status, PostgresNodeRepository.insert
# END_CONTRACT: test_repo_task_list_ids_by_node_id_and_status
async def test_repo_task_list_ids_by_node_id_and_status(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """list_ids_by_node_id_and_status filters by allocated_node_id and status."""
    task_repo = PostgresTaskRepository(pg_conn, pg_executor)
    node_repo = PostgresNodeRepository(pg_conn, pg_executor)

    node = await node_repo.insert(NewNode(hostname="10.0.0.99", ncpus=2, enabled=True))
    other = await node_repo.insert(NewNode(hostname="10.0.0.98", ncpus=2, enabled=True))

    # t1: a RUNNING task on `node` (CHECK-valid: allocated_node_id +
    # remote_folder set). The query is exercised against RUNNING, which is
    # the production usage (_remove_node_hard/_soft look up RUNNING tasks).
    t1 = await task_repo.insert(NewTask(label="for-node", engine="fleur"))
    t1 = t1.run(node.node_id, "/r/t1")
    await task_repo.save(t1)

    # t2: a RUNNING task on `other` (should NOT match the node query).
    t2 = await task_repo.insert(NewTask(label="other-node", engine="fleur"))
    t2 = t2.run(other.node_id, "/r/t2")
    await task_repo.save(t2)

    # t3: a DONE task on `node` (CHECK-valid: DONE is unconstrained), built
    # via the real lifecycle so every persisted state satisfies the CHECK.
    t3 = await task_repo.insert(NewTask(label="done-on-node", engine="fleur"))
    t3 = t3.run(node.node_id, "/r/t3")
    await task_repo.save(t3)
    t3_done = t3.complete(local_folder="/l", remote_folder="/r/t3")
    await task_repo.save(t3_done)

    ids = await task_repo.list_ids_by_node_id_and_status(
        node.node_id, DomainTaskStatus.RUNNING
    )
    assert ids == [t1.task_id]


# ====================================================================
# Task 8.3: PostgresNodeRepository
# ====================================================================


# START_CONTRACT: test_repo_node_crud
#   PURPOSE: Verify full node CRUD lifecycle: add, get, enable, disable, remove.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresNodeRepository.add, get, enable, disable, remove
# END_CONTRACT: test_repo_node_crud
async def test_repo_node_crud(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """Full node lifecycle through repository."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)

    new_node = NewNode(
        hostname="10.0.0.10",
        ncpus=4,
        enabled=True,
        cloud="aws",
        username="admin",
        port=2222,
    )
    persisted = await repo.insert(new_node)
    assert isinstance(persisted, Node)
    assert isinstance(persisted.node_id, NodeId)
    assert persisted.node_id.value >= 1

    # Get
    retrieved = await repo.get_by_id(persisted.node_id)
    assert retrieved is not None
    assert retrieved.ncpus == 4
    assert retrieved.cloud == "aws"
    assert retrieved.username == "admin"
    assert retrieved.port == 2222
    assert retrieved.enabled is True

    # Disable
    await repo.disable(persisted.node_id)
    n = await repo.get_by_id(persisted.node_id)
    assert n is not None and n.enabled is False

    # Enable
    await repo.enable(persisted.node_id)
    n = await repo.get_by_id(persisted.node_id)
    assert n is not None and n.enabled is True

    # Remove
    await repo.remove(persisted.node_id)
    assert await repo.get_by_id(persisted.node_id) is None


# START_CONTRACT: test_repo_node_list_filters
#   PURPOSE: Verify list_enabled and list_disabled return correct subsets.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresNodeRepository.list_enabled, list_disabled, list_all
# END_CONTRACT: test_repo_node_list_filters
async def test_repo_node_list_filters(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """list_enabled/disabled return correct subsets."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)
    await repo.insert(NewNode(hostname="10.0.0.1", ncpus=2, enabled=True))
    await repo.insert(NewNode(hostname="10.0.0.2", ncpus=2, enabled=False))

    enabled = await repo.list_enabled()
    disabled = await repo.list_disabled()
    all_nodes = await repo.list_all()

    assert len(enabled) == 1 and enabled[0].hostname == "10.0.0.1"
    assert len(disabled) == 1 and disabled[0].hostname == "10.0.0.2"
    assert len(all_nodes) == 2


# START_CONTRACT: test_repo_node_update
#   PURPOSE: Verify update() persists all mutable node fields.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresNodeRepository.update
# END_CONTRACT: test_repo_node_update
async def test_repo_node_update(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """update persists all mutable fields (including ip — V1 cloud lifecycle relies on this)."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)
    # Insert with ip="" mirroring the tmp-reservation row (NewNode cloud defaults).
    persisted = await repo.insert(
        NewNode(hostname="", ncpus=None, enabled=False, cloud="aws")
    )

    # Flip to enabled=True + real hostname/ncpus via update (the V1 single-row lifecycle).
    await repo.update(
        Node(
            node_id=NodeId(persisted.node_id.value),
            hostname="10.0.0.1",
            ncpus=8,
            enabled=True,
            cloud="azure",
            username="admin",
            port=2222,
        )
    )
    n = await repo.get_by_id(persisted.node_id)
    assert n is not None
    assert n.hostname == "10.0.0.1", (
        "update must persist ip (V1 cloud lifecycle sets real ip via update)"
    )
    assert n.ncpus == 8
    assert n.enabled is True
    assert n.cloud == "azure"
    assert n.username == "admin"
    assert n.port == 2222


# START_CONTRACT: test_repo_node_tmp_via_insert
#   PURPOSE: Verify insert(NewNode(cloud=..., enabled=False)) inserts a tmp row carrying ip="" sentinel and node_id (add_tmp abolished).
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresNodeRepository.insert
# END_CONTRACT: test_repo_node_tmp_via_insert
async def test_repo_node_tmp_via_insert(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """insert(NewNode(cloud=..., enabled=False)) inserts a tmp row with ip="" and node_id."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)
    node = await repo.insert(NewNode(cloud="aws", enabled=False))
    assert isinstance(node, Node)
    assert isinstance(node.node_id, NodeId)
    assert node.node_id.value >= 1
    assert node.hostname == ""
    assert node.enabled is False
    assert node.cloud == "aws"
    assert node.username == "root"
    assert node.port == 22


# START_CONTRACT: test_repo_node_count
#   PURPOSE: Verify count_by_cloud and count_by_status return correct aggregates.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresNodeRepository.count_by_cloud, count_by_status
# END_CONTRACT: test_repo_node_count
async def test_repo_node_count(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """Count aggregations work correctly."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)
    await repo.insert(NewNode(hostname="10.0.0.1", ncpus=2, cloud="aws", enabled=True))
    await repo.insert(NewNode(hostname="10.0.0.2", ncpus=2, cloud="aws", enabled=False))
    await repo.insert(
        NewNode(hostname="10.0.0.3", ncpus=2, cloud="azure", enabled=True)
    )

    clouds = await repo.count_by_cloud()
    assert clouds["aws"] == 2
    assert clouds["azure"] == 1

    statuses = await repo.count_by_status()
    assert statuses[True] == 2
    assert statuses[False] == 1


# START_CONTRACT: test_repo_node_get_by_ids
#   PURPOSE: Verify batch get_by_ids returns all matching nodes keyed by NodeId.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresNodeRepository.get_by_ids
# END_CONTRACT: test_repo_node_get_by_ids
async def test_repo_node_get_by_ids(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """Batch get_by_ids returns only matching nodes keyed by NodeId."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)
    n1 = await repo.insert(NewNode(hostname="10.0.0.1", ncpus=2, cloud="aws"))
    await repo.insert(NewNode(hostname="10.0.0.2", ncpus=2, cloud="gcp"))
    n3 = await repo.insert(NewNode(hostname="10.0.0.3", ncpus=2, cloud="azure"))

    nodes = await repo.get_by_ids([n1.node_id, n3.node_id, NodeId(99999)])
    assert len(nodes) == 2
    assert nodes[n1.node_id].cloud == "aws"
    assert nodes[n3.node_id].cloud == "azure"
    assert NodeId(99999) not in nodes


# START_CONTRACT: test_repo_node_get_by_id
#   PURPOSE: Verify get_by_id lookup by primary key, including None for non-existing id.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresNodeRepository.get_by_id
# END_CONTRACT: test_repo_node_get_by_id
async def test_repo_node_get_by_id(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """get_by_id returns node by primary key, None for missing id."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)
    persisted = await repo.insert(
        NewNode(hostname="10.0.0.20", ncpus=4, enabled=True, cloud="aws")
    )

    fetched = await repo.get_by_id(persisted.node_id)
    assert fetched is not None
    assert fetched.node_id == persisted.node_id
    assert fetched.hostname == "10.0.0.20"
    assert fetched.ncpus == 4
    assert fetched.cloud == "aws"

    missing = await repo.get_by_id(NodeId(99999))
    assert missing is None


async def test_repo_node_get_by_ids_empty(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """get_by_ids([]) returns empty dict."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)
    assert await repo.get_by_ids([]) == {}


# START_CONTRACT: test_repo_node_list_all_ordered_by_node_id
#   PURPOSE: Verify list_all returns nodes sorted by node_id ascending.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresNodeRepository.list_all
# END_CONTRACT: test_repo_node_list_all_ordered_by_node_id
async def test_repo_node_list_all_ordered_by_node_id(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """list_all returns nodes ordered by node_id ascending."""
    repo = PostgresNodeRepository(pg_conn, pg_executor)
    await repo.insert(NewNode(hostname="10.0.0.1", ncpus=2))
    await repo.insert(NewNode(hostname="10.0.0.2", ncpus=2))
    await repo.insert(NewNode(hostname="10.0.0.3", ncpus=2))

    all_nodes = await repo.list_all()
    node_ids = [n.node_id.value for n in all_nodes]
    assert node_ids == sorted(node_ids)


# ====================================================================
# Task 8.4: PostgresUnitOfWork
# ====================================================================


# START_CONTRACT: test_uow_integration
#   PURPOSE: Verify UoW creates repos and allows commit.
#   INPUTS: { _db_config: PostgresDbConfig - session database config, _init_schema: None - schema initialized }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Creates and closes pg8000 connections; commits a node insert.
#   LINKS: PostgresUnitOfWork
# END_CONTRACT: test_uow_integration
async def test_uow_integration(
    _db_config: PostgresDbConfig, _init_schema: None
) -> None:
    """UoW creates repos from config, commit persists, exit closes."""

    config: PostgresDbConfig = _db_config

    async with PostgresUnitOfWork(config, MessageBus()) as uow:
        assert uow.tasks is not None
        assert uow.nodes is not None

        # Insert through repo
        new_node = NewNode(hostname="10.0.0.50", ncpus=2, enabled=True)
        persisted = await uow.nodes.insert(new_node)
        await uow.commit()
        assert isinstance(persisted, Node)
        assert isinstance(persisted.node_id, NodeId)
        assert persisted.node_id.value >= 1

        # Verify persisted
        retrieved = await uow.nodes.get_by_id(persisted.node_id)
        assert retrieved is not None
        assert retrieved.hostname == "10.0.0.50"


# START_CONTRACT: test_uow_rollback_integration
#   PURPOSE: Verify rollback on exception discards uncommitted changes.
#   INPUTS: { _db_config: PostgresDbConfig - session database config, _init_schema: None - schema initialized }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Creates and closes pg8000 connections; rolls back on exception.
#   LINKS: PostgresUnitOfWork
# END_CONTRACT: test_uow_rollback_integration
async def test_uow_rollback_integration(
    _db_config: PostgresDbConfig, _init_schema: None
) -> None:
    """Uncommitted changes are lost on rollback."""

    config: PostgresDbConfig = _db_config

    with pytest.raises(ValueError):
        async with PostgresUnitOfWork(config, MessageBus()) as uow:
            persisted = await uow.nodes.insert(
                NewNode(hostname="10.0.0.99", ncpus=2, enabled=True)
            )
            raise ValueError("simulated error")

    # After rollback, node should NOT exist
    async with PostgresUnitOfWork(config, MessageBus()) as uow:
        n = await uow.nodes.get_by_id(persisted.node_id)
        assert n is None


# ====================================================================
# Task 8.5: DB wrapper coverage
# ====================================================================
# Coverage for the DB wrapper (PostgresTaskRepository/PostgresNodeRepository
# through DB._task_repo / DB._node_repo) is provided by test_db_integration.py.
# Tests 8.2-8.4 above cover the repository and UoW layer directly.
# See test_db_integration.py for DB-level integration coverage.
