# FILE: tests/integration/test_db_integration.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for PostgresUnitOfWork + repositories against real PostgreSQL via testcontainers.
#   SCOPE: Node CRUD, Task CRUD, status transitions, UoW-based composition queries (list_by_jobs, get_by_ips, add_tmp).
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
#   test_task_lifecycle - insert -> allocate_to/mark_running -> DONE with metadata merge
#   test_set_task_error - with and without error message
#   test_get_tasks_by_status - filtering across statuses
#   test_get_tasks_by_jobs - array parameter with unnest
#   test_get_task_ids_by_ip_and_status - filtered by IP and status
#   test_get_tasks_with_cloud_by_id_status - in-test composition: list_by_jobs + get_by_ips
#   test_add_tmp_node - provisional IP, disabled, correct cloud/username
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Rewrite from DB facade to PostgresUnitOfWork + repos (remove-legacy-db).
# END_CHANGE_SUMMARY

"""Integration tests for PostgresUnitOfWork + repositories against real PostgreSQL."""

from collections.abc import Callable

from yascheduler.domain.model import Node, Task, TaskContext
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
    node = Node(
        ip="10.0.0.1", username="admin", port=2222, ncpus=8, cloud="azure", enabled=True
    )
    assert node.ip == "10.0.0.1"
    assert node.username == "admin"
    assert node.port == 2222
    assert node.ncpus == 8
    assert node.cloud == "azure"
    assert node.enabled is True

    async with uow_factory() as uow:
        await uow.nodes.add(node)
        await uow.commit()

    async with uow_factory() as uow:
        retrieved = await uow.nodes.get("10.0.0.1")
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
        await uow.nodes.add(Node(ip="10.0.0.1", ncpus=0, enabled=True))
        await uow.nodes.add(Node(ip="10.0.0.2", ncpus=0, enabled=False))
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
        await uow.nodes.add(Node(ip="10.0.0.1", ncpus=0))
        await uow.commit()

    async with uow_factory() as uow:
        assert bool(await uow.nodes.get("10.0.0.1")) is True
        assert await uow.nodes.get("10.0.0.99") is None


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
        await uow.nodes.add(Node(ip="10.0.0.1", ncpus=0, enabled=False))
        await uow.commit()

    async with uow_factory() as uow:
        await uow.nodes.enable("10.0.0.1")
        await uow.commit()

    async with uow_factory() as uow:
        node = await uow.nodes.get("10.0.0.1")
        assert node is not None
        assert node.enabled is True

    async with uow_factory() as uow:
        await uow.nodes.disable("10.0.0.1")
        await uow.commit()

    async with uow_factory() as uow:
        node = await uow.nodes.get("10.0.0.1")
        assert node is not None
        assert node.enabled is False


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
        await uow.nodes.add(Node(ip="10.0.0.1", ncpus=0))
        await uow.commit()

    async with uow_factory() as uow:
        assert bool(await uow.nodes.get("10.0.0.1")) is True
        await uow.nodes.remove("10.0.0.1")
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.nodes.get("10.0.0.1") is None


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
        await uow.nodes.add(Node(ip="10.0.0.1", ncpus=0, cloud="azure", enabled=True))
        await uow.nodes.add(Node(ip="10.0.0.2", ncpus=0, cloud="azure", enabled=False))
        await uow.nodes.add(Node(ip="10.0.0.3", ncpus=0, cloud="hetzner", enabled=True))
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
        task = await uow.tasks.insert(
            Task(
                task_id=0,
                label="calc",
                context=ctx,
                status=DomainTaskStatus.TO_DO,
                allocated_ip="10.0.0.1",
            )
        )
        await uow.commit()
        assert task.task_id >= 1
        assert task.label == "calc"
        assert task.allocated_ip == "10.0.0.1"
        assert task.status == DomainTaskStatus.TO_DO
        assert task.context.to_metadata() == {**meta, "param": 42}

    async with uow_factory() as uow:
        retrieved = await uow.tasks.get(task.task_id)
        assert retrieved is not None
        assert retrieved.task_id == task.task_id
        assert retrieved.label == "calc"
        assert retrieved.allocated_ip == "10.0.0.1"
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
        task = await uow.tasks.insert(
            Task(task_id=0, label="sim", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.commit()
        assert task.status == DomainTaskStatus.TO_DO
        task_id = task.task_id

    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
        assert task is not None
        updated = task.allocate_to("10.0.0.5").mark_running()
        await uow.tasks.save(updated)
        await uow.commit()

    async with uow_factory() as uow:
        running = await uow.tasks.get(task_id)
        assert running is not None
        assert running.status == DomainTaskStatus.RUNNING
        assert running.allocated_ip == "10.0.0.5"

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
            allocated_ip=task.allocated_ip,
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
            Task(
                task_id=0, label="fail-job", context=ctx, status=DomainTaskStatus.TO_DO
            )
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
            allocated_ip=task.allocated_ip,
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
            Task(
                task_id=0, label="fail-job2", context=ctx, status=DomainTaskStatus.TO_DO
            )
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
            allocated_ip=task2.allocated_ip,
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
            Task(task_id=0, label="todo", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.tasks.insert(
            Task(
                task_id=0, label="running", context=ctx, status=DomainTaskStatus.RUNNING
            )
        )
        await uow.tasks.insert(
            Task(task_id=0, label="done", context=ctx, status=DomainTaskStatus.DONE)
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
            Task(task_id=0, label="a", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.tasks.insert(
            Task(task_id=0, label="b", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        t3 = await uow.tasks.insert(
            Task(task_id=0, label="c", context=ctx, status=DomainTaskStatus.TO_DO)
        )
        await uow.commit()

    async with uow_factory() as uow:
        results = await uow.tasks.list_by_jobs([t1.task_id, t3.task_id])
        assert len(results) == 2
        ids = {r.task_id for r in results}
        assert ids == {t1.task_id, t3.task_id}


# START_CONTRACT: test_get_task_ids_by_ip_and_status
#   PURPOSE: Verify filtering task IDs by IP address and status.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_get_task_ids_by_ip_and_status
async def test_get_task_ids_by_ip_and_status(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Filter task IDs by IP and status."""
    ip = "192.168.1.1"
    ctx = TaskContext(engine="fleur")
    async with uow_factory() as uow:
        t1 = await uow.tasks.insert(
            Task(
                task_id=0,
                label="x",
                context=ctx,
                status=DomainTaskStatus.RUNNING,
                allocated_ip=ip,
            )
        )
        await uow.tasks.insert(
            Task(
                task_id=0,
                label="y",
                context=ctx,
                status=DomainTaskStatus.RUNNING,
                allocated_ip="10.0.0.1",
            )
        )
        await uow.tasks.insert(
            Task(
                task_id=0,
                label="z",
                context=ctx,
                status=DomainTaskStatus.DONE,
                allocated_ip=ip,
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        ids = await uow.tasks.list_ids_by_ip_and_status(ip, DomainTaskStatus.RUNNING)
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
    """Compose list_by_jobs + get_by_ips to get cloud attribute."""
    ctx = TaskContext(engine="fleur")
    async with uow_factory() as uow:
        await uow.nodes.add(Node(ip="10.0.0.1", ncpus=0, cloud="azure", enabled=True))
        await uow.commit()

    async with uow_factory() as uow:
        t = await uow.tasks.insert(
            Task(
                task_id=0,
                label="",
                context=ctx,
                status=DomainTaskStatus.RUNNING,
                allocated_ip="10.0.0.1",
            )
        )
        t2 = await uow.tasks.insert(
            Task(
                task_id=0,
                label="",
                context=ctx,
                status=DomainTaskStatus.DONE,
                allocated_ip="10.0.0.1",
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        tasks = await uow.tasks.list_by_jobs([t.task_id, t2.task_id])
        matching = [task for task in tasks if task.status == DomainTaskStatus.RUNNING]
        assert len(matching) == 1
        assert matching[0].task_id == t.task_id
        ips = [task.allocated_ip for task in matching if task.allocated_ip]
        nodes = await uow.nodes.get_by_ips(ips)
        assert matching[0].allocated_ip is not None
        node = nodes.get(matching[0].allocated_ip)
        assert node is not None
        assert node.cloud == "azure"


# ---------------------------------------------------------------------------
# PostgreSQL-specific features
# ---------------------------------------------------------------------------


# START_CONTRACT: test_add_tmp_node
#   PURPOSE: Verify add_tmp generates a provisional IP and inserts a disabled node.
#   INPUTS: { uow_factory: UoW factory fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-POSTGRES
# END_CONTRACT: test_add_tmp_node
async def test_add_tmp_node(uow_factory: Callable[[], PostgresUnitOfWork]) -> None:
    """add_tmp creates a disabled node with provisional IP."""
    async with uow_factory() as uow:
        ip = await uow.nodes.add_tmp("azure", "root")
        await uow.commit()
        assert ip.startswith("prov")

    async with uow_factory() as uow:
        node = await uow.nodes.get(ip)
        assert node is not None
        assert node.enabled is False
        assert node.cloud == "azure"
        assert node.username == "root"
