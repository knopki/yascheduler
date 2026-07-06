# FILE: tests/integration/test_db_integration.py
# VERSION: 2.4.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for PostgresUnitOfWork + repositories against real PostgreSQL via testcontainers.
#   SCOPE: Node CRUD, Task CRUD, status transitions, UoW-based composition queries (list_by_jobs, get_by_ids), tmp-node lifecycle via insert, migration 003 backfill + constraint drop, migration 004 pre-create table at 002-era schema (so 004 ALTER ADD COLUMN is valid).
#   DEPENDS: M-PERSISTENCE-UOW, M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL, M-CONFIG-DB
#   LINKS: M-PERSISTENCE-UOW, M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_add_and_get_node - round-trip add + get via Node domain object
#   test_get_all_nodes_filtering - list_all, list_enabled, list_disabled
#   test_has_node - existing and non-existing IP
#   test_enable_disable_node - toggling enabled status via repo
#   test_remove_node - node removed after removal
#   test_count_aggregations - count_by_cloud, count_by_status
#   test_add_and_get_task - round-trip insert + get with JSONB metadata
#   test_task_lifecycle - insert -> allocate_to(node)/mark_running -> DONE with metadata merge (preserves allocated_node_id)
#   test_set_task_error - with and without error message
#   test_get_tasks_by_status - filtering across statuses
#   test_get_tasks_by_jobs - array parameter with unnest
#   test_get_task_ids_by_node_id_and_status - filtered by node_id and status
#   test_get_tasks_with_cloud_by_id_status - in-test composition: list_by_jobs + get_by_ips
#   test_tmp_node_lifecycle_via_insert - tmp-node inserted via insert(NewNode(cloud=..., enabled=False)) carries ip="", enabled=False, node_id; remove cleans up
#   test_migration_003_backfills_prov_ips_and_drops_unique - migration 003 backfills prov... → '' and drops yascheduler_nodes_ip_key; pre-creates yascheduler_tasks at 002-era schema so 004 ALTER is valid
#   test_list_filters_empty_ip_in_sql - list_enabled/list_disabled exclude ip='' rows at the SQL layer (no python post-filter)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.4.0 - task-schema-and-entity-cleanup: removed all allocated_ip references; test_add_and_get_task uses allocated_node_id; test_task_lifecycle no longer asserts allocated_ip; test_set_task_error removes allocated_ip from Task construction; test_get_task_ids_by_ip_and_status → test_get_task_ids_by_node_id_and_status (uses list_ids_by_node_id_and_status); test_get_tasks_with_cloud_by_id_status uses allocated_node_id for node resolution.
#   PREVIOUS_CHANGE: v2.3.0 - task-allocated-node-id: test_task_lifecycle inserts a Node and calls allocate_to(node) (was allocate_to(ip) — signature changed); the DONE transition preserves allocated_node_id from the loaded task (manual Task construction passes allocated_node_id=task.allocated_node_id). test_migration_003_backfills_prov_ips_and_drops_unique pre-creates yascheduler_tasks at the 002-era schema (no allocated_node_id) so migration 004's ALTER ADD COLUMN does not collide with the fresh-snapshot CREATE TABLE. The schema now seeds to migration 003 and drops ip UNIQUE.
# END_CHANGE_SUMMARY

"""Integration tests for PostgresUnitOfWork + repositories against real PostgreSQL."""

from collections.abc import Callable

from yascheduler.domain.model import (
    NewNode,
    NewTask,
    Node,
    NodeId,
    Task,
    TaskContext,
)
from yascheduler.domain.model import TaskStatus as DomainTaskStatus
from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------


# START_CONTRACT: test_add_and_get_node
#   PURPOSE: Verify Node add + get round-trip with all fields via UoW.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL
# END_CONTRACT: test_add_and_get_node
async def test_add_and_get_node(uow_factory: Callable[[], PostgresUnitOfWork]) -> None:
    """Insert a node and retrieve it; verify all fields match."""
    new_node = NewNode(
        ip="10.0.0.1", username="admin", port=2222, ncpus=8, cloud="azure", enabled=True
    )
    assert new_node.ip == "10.0.0.1"
    assert new_node.username == "admin"
    assert new_node.port == 2222
    assert new_node.ncpus == 8
    assert new_node.cloud == "azure"
    assert new_node.enabled is True

    async with uow_factory() as uow:
        persisted = await uow.nodes.insert(new_node)
        await uow.commit()
        assert isinstance(persisted, Node)
        assert isinstance(persisted.node_id, NodeId)
        assert persisted.node_id.value >= 1

    async with uow_factory() as uow:
        retrieved = await uow.nodes.get_by_id(persisted.node_id)
        assert retrieved is not None
        assert retrieved.ip == "10.0.0.1"
        assert retrieved.username == "admin"
        assert retrieved.port == 2222
        assert retrieved.ncpus == 8
        assert retrieved.cloud == "azure"
        assert retrieved.enabled is True


# START_CONTRACT: test_get_all_nodes_filtering
#   PURPOSE: Verify list_all, list_enabled, list_disabled filtering via UoW.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_get_all_nodes_filtering
async def test_get_all_nodes_filtering(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Add enabled and disabled nodes; verify filtered queries."""
    async with uow_factory() as uow:
        await uow.nodes.insert(NewNode(ip="10.0.0.1", ncpus=0, enabled=True))
        await uow.nodes.insert(NewNode(ip="10.0.0.2", ncpus=0, enabled=False))
        await uow.commit()

    async with uow_factory() as uow:
        all_nodes = await uow.nodes.list_all()
        assert len(all_nodes) == 2

        enabled = await uow.nodes.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].ip == "10.0.0.1"

        disabled = await uow.nodes.list_disabled()
        assert len(disabled) == 1
        assert disabled[0].ip == "10.0.0.2"


# START_CONTRACT: test_has_node
#   PURPOSE: Verify get() returns node for existing IP and None for non-existing.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_has_node
async def test_has_node(uow_factory: Callable[[], PostgresUnitOfWork]) -> None:
    """Check has_node for existing and non-existing IPs."""
    async with uow_factory() as uow:
        node = await uow.nodes.insert(NewNode(ip="10.0.0.1", ncpus=0))
        await uow.commit()

    async with uow_factory() as uow:
        assert bool(await uow.nodes.get_by_id(node.node_id)) is True
        assert await uow.nodes.get_by_id(NodeId(99999)) is None


# START_CONTRACT: test_enable_disable_node
#   PURPOSE: Verify enable/disable toggle the enabled flag via repo.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_enable_disable_node
async def test_enable_disable_node(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Toggle node enabled status and verify."""
    async with uow_factory() as uow:
        node = await uow.nodes.insert(NewNode(ip="10.0.0.1", ncpus=0, enabled=False))
        await uow.commit()

    async with uow_factory() as uow:
        await uow.nodes.enable(node.node_id)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.nodes.get_by_id(node.node_id)
        assert fetched is not None
        assert fetched.enabled is True

    async with uow_factory() as uow:
        await uow.nodes.disable(node.node_id)
        await uow.commit()

    async with uow_factory() as uow:
        fetched = await uow.nodes.get_by_id(node.node_id)
        assert fetched is not None
        assert fetched.enabled is False


# START_CONTRACT: test_remove_node
#   PURPOSE: Verify remove deletes the node; get returns None after removal.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_remove_node
async def test_remove_node(uow_factory: Callable[[], PostgresUnitOfWork]) -> None:
    """Remove a node and verify it is gone."""
    async with uow_factory() as uow:
        node = await uow.nodes.insert(NewNode(ip="10.0.0.1", ncpus=0))
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.nodes.get_by_id(node.node_id) is not None
        await uow.nodes.remove(node.node_id)
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.nodes.get_by_id(node.node_id) is None


# START_CONTRACT: test_count_aggregations
#   PURPOSE: Verify count_by_cloud and count_by_status aggregation via repo.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_count_aggregations
async def test_count_aggregations(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Verify cloud and status aggregation queries."""
    async with uow_factory() as uow:
        await uow.nodes.insert(
            NewNode(ip="10.0.0.1", ncpus=0, cloud="azure", enabled=True)
        )
        await uow.nodes.insert(
            NewNode(ip="10.0.0.2", ncpus=0, cloud="azure", enabled=False)
        )
        await uow.nodes.insert(
            NewNode(ip="10.0.0.3", ncpus=0, cloud="hetzner", enabled=True)
        )
        await uow.commit()

    async with uow_factory() as uow:
        clouds = await uow.nodes.count_by_cloud()
        assert clouds == {"azure": 2, "hetzner": 1}

        by_status = await uow.nodes.count_by_status()
        assert by_status[True] == 2
        assert by_status[False] == 1


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------


# START_CONTRACT: test_add_and_get_task
#   PURPOSE: Verify Task insert + get round-trip including metadata via UoW.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL
# END_CONTRACT: test_add_and_get_task
async def test_add_and_get_task(uow_factory: Callable[[], PostgresUnitOfWork]) -> None:
    """Add a task and retrieve it; verify all fields including metadata."""
    meta: dict[str, object] = {"engine": "fleur", "webhook_custom_params": {}}
    ctx = TaskContext.from_metadata({**meta, "param": 42})

    async with uow_factory() as uow:
        node = await uow.nodes.insert(NewNode(ip="10.0.0.1", ncpus=4, enabled=True))
        task = await uow.tasks.insert(
            NewTask(
                label="calc",
                context=ctx,
                status=DomainTaskStatus.TO_DO,
                allocated_node_id=node.node_id,
            )
        )
        await uow.commit()
        assert task.task_id.value >= 1
        assert task.label == "calc"
        assert task.allocated_node_id == node.node_id
        assert task.status == DomainTaskStatus.TO_DO
        assert task.context.to_metadata() == {**meta, "param": 42}

    async with uow_factory() as uow:
        retrieved = await uow.tasks.get(task.task_id)
        assert retrieved is not None
        assert retrieved.task_id == task.task_id
        assert retrieved.label == "calc"
        assert retrieved.allocated_node_id == node.node_id
        assert retrieved.status == DomainTaskStatus.TO_DO
        assert retrieved.context.to_metadata() == {**meta, "param": 42}


# START_CONTRACT: test_task_lifecycle
#   PURPOSE: Verify full task lifecycle: insert -> allocate_to/mark_running -> DONE with metadata merge.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL
# END_CONTRACT: test_task_lifecycle
async def test_task_lifecycle(uow_factory: Callable[[], PostgresUnitOfWork]) -> None:
    """Walk a task through TO_DO -> RUNNING -> DONE and verify each step."""
    meta: dict[str, object] = {"engine": "fleur", "webhook_custom_params": {}}
    ctx = TaskContext.from_metadata(meta)

    async with uow_factory() as uow:
        # Insert a node first so allocate_to(node) can bind a real node_id
        # (the DB FK allocated_node_id REFERENCES yascheduler_nodes(node_id)).
        node = await uow.nodes.insert(NewNode(ip="10.0.0.5", ncpus=4, enabled=True))
        task = await uow.tasks.insert(
            NewTask(label="sim", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.commit()
        assert task.status == DomainTaskStatus.TO_DO
        task_id = task.task_id
        node_id = node.node_id

    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
        assert task is not None
        # Construct the Node for allocate_to using the DB-assigned node_id.
        alloc_node = Node(node_id=node_id, ip="10.0.0.5", ncpus=4)
        updated = task.allocate_to(alloc_node).mark_running()
        await uow.tasks.save(updated)
        await uow.commit()

    async with uow_factory() as uow:
        running = await uow.tasks.get(task_id)
        assert running is not None
        assert running.status == DomainTaskStatus.RUNNING
        assert running.allocated_node_id == node_id

    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
        assert task is not None
        merged = task.context.to_metadata()
        merged["result"] = "ok"
        updated = Task(
            task_id=task.task_id,
            label=task.label,
            context=TaskContext.from_metadata(merged),
            status=DomainTaskStatus.DONE,
            allocated_node_id=task.allocated_node_id,
        )
        await uow.tasks.save(updated)
        await uow.commit()

    async with uow_factory() as uow:
        done = await uow.tasks.get(task_id)
        assert done is not None
        assert done.status == DomainTaskStatus.DONE
        assert done.context.to_metadata() == {**meta, "result": "ok"}


# START_CONTRACT: test_set_task_error
#   PURPOSE: Verify setting task error embeds error in metadata; without error passes metadata unchanged.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL
# END_CONTRACT: test_set_task_error
async def test_set_task_error(uow_factory: Callable[[], PostgresUnitOfWork]) -> None:
    """set_task_error embeds error in metadata; without error passes metadata unchanged."""
    meta: dict[str, object] = {"engine": "fleur", "webhook_custom_params": {}}
    ctx = TaskContext.from_metadata(meta)

    # With error message
    async with uow_factory() as uow:
        task = await uow.tasks.insert(
            NewTask(label="fail-job", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.commit()
        task_id = task.task_id

    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
        assert task is not None
        merged = task.context.to_metadata()
        merged["key"] = "val"
        merged["error"] = "crash"
        updated = Task(
            task_id=task.task_id,
            label=task.label,
            context=TaskContext.from_metadata(merged),
            status=DomainTaskStatus.DONE,
            allocated_node_id=task.allocated_node_id,
        )
        await uow.tasks.save(updated)
        await uow.commit()

    async with uow_factory() as uow:
        t = await uow.tasks.get(task_id)
        assert t is not None
        assert t.status == DomainTaskStatus.DONE
        assert t.context.to_metadata() == {**meta, "key": "val", "error": "crash"}

    # Without error message (use a new task for clarity)
    async with uow_factory() as uow:
        task2 = await uow.tasks.insert(
            NewTask(label="fail-job2", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.commit()
        task2_id = task2.task_id

    async with uow_factory() as uow:
        task2 = await uow.tasks.get(task2_id)
        assert task2 is not None
        merged = task2.context.to_metadata()
        merged["only"] = "meta"
        updated = Task(
            task_id=task2.task_id,
            label=task2.label,
            context=TaskContext.from_metadata(merged),
            status=DomainTaskStatus.DONE,
            allocated_node_id=task2.allocated_node_id,
        )
        await uow.tasks.save(updated)
        await uow.commit()

    async with uow_factory() as uow:
        t2 = await uow.tasks.get(task2_id)
        assert t2 is not None
        assert t2.status == DomainTaskStatus.DONE
        assert t2.context.to_metadata() == {**meta, "only": "meta"}


# START_CONTRACT: test_get_tasks_by_status
#   PURPOSE: Verify list_by_status filters correctly by status values.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_get_tasks_by_status
async def test_get_tasks_by_status(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Filter tasks by status; multiple statuses supported."""
    ctx = TaskContext(engine="fleur")
    async with uow_factory() as uow:
        await uow.tasks.insert(
            NewTask(label="todo", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.tasks.insert(
            NewTask(label="running", context=ctx, status=DomainTaskStatus.RUNNING)
        )
        await uow.tasks.insert(
            NewTask(label="done", context=ctx, status=DomainTaskStatus.DONE)
        )
        await uow.commit()

    async with uow_factory() as uow:
        todo = await uow.tasks.list_by_status({DomainTaskStatus.TO_DO})
        assert len(todo) == 1
        assert todo[0].label == "todo"

        running = await uow.tasks.list_by_status({DomainTaskStatus.RUNNING})
        assert len(running) == 1
        assert running[0].label == "running"

        done = await uow.tasks.list_by_status({DomainTaskStatus.DONE})
        assert len(done) == 1
        assert done[0].label == "done"

        # Multiple statuses
        multi = await uow.tasks.list_by_status(
            {DomainTaskStatus.TO_DO, DomainTaskStatus.DONE}
        )
        assert len(multi) == 2


# START_CONTRACT: test_get_tasks_by_jobs
#   PURPOSE: Verify list_by_jobs uses unnest to filter by task IDs array.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_get_tasks_by_jobs
async def test_get_tasks_by_jobs(uow_factory: Callable[[], PostgresUnitOfWork]) -> None:
    """Retrieve tasks by array of IDs; only requested IDs returned."""
    ctx = TaskContext(engine="fleur")
    async with uow_factory() as uow:
        t1 = await uow.tasks.insert(
            NewTask(label="a", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.tasks.insert(
            NewTask(label="b", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        t3 = await uow.tasks.insert(
            NewTask(label="c", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.commit()

    async with uow_factory() as uow:
        results = await uow.tasks.list_by_jobs([t1.task_id, t3.task_id])
        assert len(results) == 2
        ids = {r.task_id for r in results}
        assert ids == {t1.task_id, t3.task_id}


# START_CONTRACT: test_get_task_ids_by_node_id_and_status
#   PURPOSE: Verify filtering task IDs by node_id and status.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_get_task_ids_by_node_id_and_status
async def test_get_task_ids_by_node_id_and_status(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Filter task IDs by node_id and status."""
    ctx = TaskContext(engine="fleur")
    async with uow_factory() as uow:
        node = await uow.nodes.insert(NewNode(ip="192.168.1.1", ncpus=4, enabled=True))
        node_id = node.node_id
        t1 = await uow.tasks.insert(
            NewTask(
                label="x",
                context=ctx,
                status=DomainTaskStatus.RUNNING,
                allocated_node_id=node_id,
            )
        )
        other_node = await uow.nodes.insert(
            NewNode(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        await uow.tasks.insert(
            NewTask(
                label="y",
                context=ctx,
                status=DomainTaskStatus.RUNNING,
                allocated_node_id=other_node.node_id,
            )
        )
        await uow.tasks.insert(
            NewTask(
                label="z",
                context=ctx,
                status=DomainTaskStatus.DONE,
                allocated_node_id=node_id,
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        ids = await uow.tasks.list_ids_by_node_id_and_status(
            node_id, DomainTaskStatus.RUNNING
        )
        assert ids == [t1.task_id]


# START_CONTRACT: test_get_tasks_with_cloud_by_id_status
#   PURPOSE: Verify in-test composition of list_by_jobs + get_by_ips for cloud attribute.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL
# END_CONTRACT: test_get_tasks_with_cloud_by_id_status
async def test_get_tasks_with_cloud_by_id_status(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Compose list_by_jobs + get_by_ids to get cloud attribute."""
    ctx = TaskContext(engine="fleur")
    async with uow_factory() as uow:
        node = await uow.nodes.insert(
            NewNode(ip="10.0.0.1", ncpus=0, cloud="azure", enabled=True)
        )
        await uow.commit()

    async with uow_factory() as uow:
        t = await uow.tasks.insert(
            NewTask(
                label="",
                context=ctx,
                status=DomainTaskStatus.RUNNING,
                allocated_node_id=node.node_id,
            )
        )
        t2 = await uow.tasks.insert(
            NewTask(
                label="",
                context=ctx,
                status=DomainTaskStatus.DONE,
                allocated_node_id=node.node_id,
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        tasks = await uow.tasks.list_by_jobs([t.task_id, t2.task_id])
        matching = [task for task in tasks if task.status == DomainTaskStatus.RUNNING]
        assert len(matching) == 1
        assert matching[0].task_id == t.task_id
        node_id = matching[0].allocated_node_id
        assert node_id is not None
        nodes = await uow.nodes.get_by_ids([node_id])
        assert nodes
        node = nodes[node_id]
        assert node.cloud == "azure"


# ---------------------------------------------------------------------------
# PostgreSQL-specific features
# ---------------------------------------------------------------------------


# START_CONTRACT: test_tmp_node_lifecycle_via_insert
#   PURPOSE: Verify insert(NewNode(cloud=..., enabled=False)) creates a tmp-node row with ip="" sentinel and enabled=False, returning a Node carrying node_id; remove(node_id) cleans up.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_tmp_node_lifecycle_via_insert
async def test_tmp_node_lifecycle_via_insert(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """insert(NewNode(cloud=..., enabled=False)) creates a tmp-node row; remove(node_id) cleans up."""
    async with uow_factory() as uow:
        node = await uow.nodes.insert(NewNode(cloud="azure", enabled=False))
        await uow.commit()
        assert isinstance(node, Node)
        assert isinstance(node.node_id, NodeId)
        assert node.node_id.value >= 1
        assert node.ip == ""
        assert node.enabled is False
        assert node.cloud == "azure"
        assert node.username == "root"
        assert node.port == 22

    async with uow_factory() as uow:
        # The tmp row is invisible to list_disabled (ip <> '' SQL filter excludes ip="").
        disabled = await uow.nodes.list_disabled()
        assert all(n.ip != "" for n in disabled)
        # But visible to list_all (counts toward capacity).
        all_nodes = await uow.nodes.list_all()
        assert any(n.node_id == node.node_id for n in all_nodes)

    async with uow_factory() as uow:
        await uow.nodes.remove(node.node_id)
        await uow.commit()

    async with uow_factory() as uow:
        all_nodes = await uow.nodes.list_all()
        assert all(n.node_id != node.node_id for n in all_nodes)


# START_CONTRACT: test_migration_003_backfills_prov_ips_and_drops_unique
#   PURPOSE: Verify migration 003 backfills prov... → '' and drops the yascheduler_nodes_ip_key UNIQUE constraint (duplicate real ip insert succeeds post-migration).
#   INPUTS: { None - starts its own PostgresContainer }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; seeds a prov... row; applies schema + migrations (003 backfills + drops constraint)
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_migration_003_backfills_prov_ips_and_drops_unique
async def test_migration_003_backfills_prov_ips_and_drops_unique() -> None:
    """Migration 003 backfills prov... → '' and drops yascheduler_nodes_ip_key."""
    from urllib.parse import urlparse

    from testcontainers.postgres import PostgresContainer

    from yascheduler.infra.persistence import PostgresDbConfig, apply_migrations
    from yascheduler.infra.persistence.postgres_schema import apply_schema

    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        url = urlparse(pg.get_connection_url())
        config = PostgresDbConfig(
            user=url.username or "test",
            password=url.password or "test",
            database=url.path.lstrip("/"),
            host=url.hostname or "localhost",
            port=url.port or 5432,
        )

        # Seed a legacy-style DB already at migration 002 (with the UNIQUE
        # constraint, a node_id column, and a prov... row that the old add_tmp
        # would have produced). The tracker is seeded to '002' so apply_migrations
        # only runs 003 (backfill + DROP CONSTRAINT).
        import pg8000.native

        conn = pg8000.native.Connection(
            user=config.user,
            host=config.host,
            database=config.database,
            port=config.port,
            password=config.password,
        )
        try:
            conn.run(
                "CREATE TABLE yascheduler_migrations "
                "(migration_id TEXT PRIMARY KEY, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES ('002')")
            conn.run(
                "CREATE TABLE yascheduler_nodes ("
                "node_id SERIAL PRIMARY KEY, ip VARCHAR(15) UNIQUE, "
                "port INTEGER DEFAULT 22, username VARCHAR(255) DEFAULT 'root', "
                "ncpus SMALLINT DEFAULT NULL, enabled BOOLEAN DEFAULT TRUE, "
                "cloud VARCHAR(32) DEFAULT NULL)"
            )
            conn.run(
                "INSERT INTO yascheduler_nodes (ip, enabled, cloud) "
                "VALUES ('provabc1234567', FALSE, 'aws')"
            )
            # Pre-create yascheduler_tasks at the 002-era schema (no
            # allocated_node_id) so apply_migrations runs 003 then 004
            # (004 ALTERs ADD COLUMN allocated_node_id — would collide with
            # the fresh-snapshot CREATE TABLE if the table were absent).
            conn.run(
                "CREATE TABLE yascheduler_tasks ("
                "task_id SERIAL PRIMARY KEY, label VARCHAR(256), "
                "metadata JSONB, ip VARCHAR(15), status SMALLINT)"
            )
        finally:
            conn.close()

        # apply_schema is a no-op on the existing tables (CREATE TABLE IF NOT
        # EXISTS); apply_migrations runs 003 (backfill + DROP CONSTRAINT) then
        # 004 (add allocated_node_id).
        apply_schema(config)
        apply_migrations(config)

        conn = pg8000.native.Connection(
            user=config.user,
            host=config.host,
            database=config.database,
            port=config.port,
            password=config.password,
        )
        try:
            conn.run("BEGIN")
            try:
                rows = conn.run(
                    "SELECT ip, enabled, cloud FROM yascheduler_nodes "
                    "WHERE cloud = 'aws'"
                )
            finally:
                conn.run("ROLLBACK")
            # The prov... row was backfilled to ''.
            assert len(rows) == 1
            assert rows[0][0] == ""
            assert rows[0][1] is False

            # The UNIQUE constraint is gone — a duplicate real ip insert succeeds.
            conn.run("BEGIN")
            try:
                conn.run(
                    "INSERT INTO yascheduler_nodes (ip, enabled, cloud) "
                    "VALUES ('10.0.0.99', TRUE, 'aws')"
                )
                conn.run(
                    "INSERT INTO yascheduler_nodes (ip, enabled, cloud) "
                    "VALUES ('10.0.0.99', TRUE, 'hetzner')"
                )
            finally:
                conn.run("ROLLBACK")
        finally:
            conn.close()


# START_CONTRACT: test_list_filters_empty_ip_in_sql
#   PURPOSE: Verify list_enabled returns only enabled rows (no python post-filter) and list_disabled excludes ip='' rows at the SQL layer (no python post-filter).
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_list_filters_empty_ip_in_sql
async def test_list_filters_empty_ip_in_sql(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """list_enabled/list_disabled filtering is in SQL, not python (remove-tmp-node-fake-ip)."""
    async with uow_factory() as uow:
        # A real enabled node (has a real ip).
        await uow.nodes.insert(NewNode(ip="10.0.0.1", ncpus=4, enabled=True))
        # A tmp/pending row (ip="", enabled=False) — excluded by list_disabled SQL.
        await uow.nodes.insert(NewNode(cloud="aws", enabled=False))
        # A real-disabled VM (ip<>"", enabled=False) — included by list_disabled.
        await uow.nodes.insert(NewNode(ip="10.0.0.2", ncpus=4, enabled=False))
        await uow.commit()

    async with uow_factory() as uow:
        enabled = await uow.nodes.list_enabled()
        # Only the enabled real node; no python post-filter needed (invariant:
        # no enabled row has ip="").
        assert len(enabled) == 1
        assert enabled[0].ip == "10.0.0.1"

        disabled = await uow.nodes.list_disabled()
        # Only the real-disabled VM (ip <> '' is filtered in SQL); the tmp row
        # with ip="" is excluded at the SQL layer.
        assert len(disabled) == 1
        assert disabled[0].ip == "10.0.0.2"

        all_nodes = await uow.nodes.list_all()
        # list_all returns everything (including the tmp row with ip="").
        assert len(all_nodes) == 3
