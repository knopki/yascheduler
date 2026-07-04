# FILE: tests/integration/test_persistence_adapter.py
# VERSION: 1.2.2
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for persistence adapter against real PostgreSQL via testcontainers.
#   SCOPE: PostgresTaskRepository CRUD, PostgresNodeRepository CRUD, PostgresUnitOfWork commit/rollback.
#   DEPENDS: M-PERSISTENCE-POSTGRES, M-PERSISTENCE-UOW, M-INFRA-DB-CONFIG
#   LINKS: M-PERSISTENCE-POSTGRES, M-PERSISTENCE-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_repo_task_insert_and_get - round-trip insert + get with JSONB metadata
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
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - remove-tmp-node-fake-ip: replace test_repo_node_add_tmp with test_repo_node_tmp_via_insert (insert(NewNode(cloud=..., enabled=False)) → Node with ip="" sentinel and node_id; add_tmp abolished).
#   PREVIOUS_CHANGE: v1.2.2 - Adapt to add-node-id-identity: Node(node_id=...) first field, NewNode for insert, repo.add→insert, NodeId assertions, add get_by_id + list_all ordering tests.
# END_CHANGE_SUMMARY

"""Integration tests for persistence adapter repositories and Unit of Work."""

from concurrent.futures import ThreadPoolExecutor

import pg8000.native
import pytest

from yascheduler.application.message_bus import MessageBus
from yascheduler.domain.model import (
    NewNode,
    NewTask,
    Node,
    NodeId,
    Task,
    TaskContext,
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
#   PURPOSE: Verify round-trip insert -> get with all TaskContext fields including JSONB roundtrip.
#   INPUTS: { pg_conn: pg8000 connection, pg_executor: thread pool executor }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: PostgresTaskRepository.insert, PostgresTaskRepository.get, TaskContext.to_metadata
# END_CONTRACT: test_repo_task_insert_and_get
async def test_repo_task_insert_and_get(
    pg_conn: pg8000.native.Connection, pg_executor: ThreadPoolExecutor
) -> None:
    """Insert a task via repo, get it back, verify all fields including JSONB roundtrip."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)

    ctx = TaskContext(
        engine="fleur",
        remote_folder="/r",
        local_folder="/l",
        webhook_url="https://hook.example.com",
        extra={"param": 42},
    )
    new_task = NewTask(label="test-task", context=ctx, status=DomainTaskStatus.TO_DO)
    inserted = await repo.insert(new_task)
    assert inserted.task_id.value >= 1
    assert inserted.label == "test-task"
    assert inserted.status == DomainTaskStatus.TO_DO
    assert inserted.context.engine == "fleur"
    assert inserted.context.remote_folder == "/r"
    assert inserted.context.webhook_url == "https://hook.example.com"
    assert inserted.context.extra["param"] == 42
    assert inserted.context.webhook_custom_params == {}

    # Retrieve by ID
    retrieved = await repo.get(inserted.task_id)
    assert retrieved is not None
    assert retrieved.task_id == inserted.task_id
    assert retrieved.label == inserted.label
    assert retrieved.context.engine == "fleur"
    assert retrieved.context.extra["param"] == 42


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
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    ctx = TaskContext(engine="fleur")
    task = await repo.insert(
        NewTask(label="initial", context=ctx, status=DomainTaskStatus.TO_DO)
    )

    updated = Task(
        task_id=task.task_id,
        label="renamed",
        context=ctx,
        status=DomainTaskStatus.RUNNING,
        allocated_ip="10.0.0.5",
    )
    await repo.save(updated)

    retrieved = await repo.get(task.task_id)
    assert retrieved is not None
    assert retrieved.label == "renamed"
    assert retrieved.status == DomainTaskStatus.RUNNING
    assert retrieved.allocated_ip == "10.0.0.5"


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
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    ctx = TaskContext(engine="fleur")
    t1 = await repo.insert(
        NewTask(label="todo", context=ctx, status=DomainTaskStatus.TO_DO)
    )
    t2_id = (
        await repo.insert(
            NewTask(label="running", context=ctx, status=DomainTaskStatus.TO_DO)
        )
    ).task_id
    await repo.save(
        Task(
            task_id=t2_id,
            label="running",
            context=ctx,
            status=DomainTaskStatus.RUNNING,
            allocated_ip="10.0.0.1",
        )
    )

    todos = await repo.list_by_status({DomainTaskStatus.TO_DO})
    assert len(todos) == 1
    assert todos[0].task_id == t1.task_id

    running = await repo.list_by_status({DomainTaskStatus.RUNNING})
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
    ctx = TaskContext(engine="fleur")
    await repo.insert(NewTask(label="t1", context=ctx, status=DomainTaskStatus.TO_DO))
    await repo.insert(NewTask(label="t2", context=ctx, status=DomainTaskStatus.TO_DO))
    await repo.insert(NewTask(label="t3", context=ctx, status=DomainTaskStatus.DONE))

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
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    ctx = TaskContext(engine="fleur")
    task = await repo.insert(
        NewTask(label="keep-label", context=ctx, status=DomainTaskStatus.TO_DO)
    )

    await repo.update_status(task.task_id, DomainTaskStatus.RUNNING)
    retrieved = await repo.get(task.task_id)
    assert retrieved is not None
    assert retrieved.status == DomainTaskStatus.RUNNING
    assert retrieved.label == "keep-label"


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
        ip="10.0.0.10", ncpus=4, enabled=True, cloud="aws", username="admin", port=2222
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
    await repo.insert(NewNode(ip="10.0.0.1", ncpus=2, enabled=True))
    await repo.insert(NewNode(ip="10.0.0.2", ncpus=2, enabled=False))

    enabled = await repo.list_enabled()
    disabled = await repo.list_disabled()
    all_nodes = await repo.list_all()

    assert len(enabled) == 1 and enabled[0].ip == "10.0.0.1"
    assert len(disabled) == 1 and disabled[0].ip == "10.0.0.2"
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
    persisted = await repo.insert(NewNode(ip="", ncpus=0, enabled=False, cloud="aws"))

    # Flip to enabled=True + real ip/ncpus via update (the V1 single-row lifecycle).
    await repo.update(
        Node(
            node_id=NodeId(persisted.node_id.value),
            ip="10.0.0.1",
            ncpus=8,
            enabled=True,
            cloud="azure",
            username="admin",
            port=2222,
        )
    )
    n = await repo.get_by_id(persisted.node_id)
    assert n is not None
    assert n.ip == "10.0.0.1", (
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
    assert node.ip == ""
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
    await repo.insert(NewNode(ip="10.0.0.1", ncpus=2, cloud="aws", enabled=True))
    await repo.insert(NewNode(ip="10.0.0.2", ncpus=2, cloud="aws", enabled=False))
    await repo.insert(NewNode(ip="10.0.0.3", ncpus=2, cloud="azure", enabled=True))

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
    n1 = await repo.insert(NewNode(ip="10.0.0.1", ncpus=2, cloud="aws"))
    await repo.insert(NewNode(ip="10.0.0.2", ncpus=2, cloud="gcp"))
    n3 = await repo.insert(NewNode(ip="10.0.0.3", ncpus=2, cloud="azure"))

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
        NewNode(ip="10.0.0.20", ncpus=4, enabled=True, cloud="aws")
    )

    fetched = await repo.get_by_id(persisted.node_id)
    assert fetched is not None
    assert fetched.node_id == persisted.node_id
    assert fetched.ip == "10.0.0.20"
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
    await repo.insert(NewNode(ip="10.0.0.1", ncpus=2))
    await repo.insert(NewNode(ip="10.0.0.2", ncpus=2))
    await repo.insert(NewNode(ip="10.0.0.3", ncpus=2))

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
        new_node = NewNode(ip="10.0.0.50", ncpus=2, enabled=True)
        persisted = await uow.nodes.insert(new_node)
        await uow.commit()
        assert isinstance(persisted, Node)
        assert isinstance(persisted.node_id, NodeId)
        assert persisted.node_id.value >= 1

        # Verify persisted
        retrieved = await uow.nodes.get_by_id(persisted.node_id)
        assert retrieved is not None
        assert retrieved.ip == "10.0.0.50"


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
                NewNode(ip="10.0.0.99", ncpus=2, enabled=True)
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
