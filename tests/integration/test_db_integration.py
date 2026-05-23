# FILE: tests/integration/test_db_integration.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for DB class against real PostgreSQL via testcontainers.
#   SCOPE: Node CRUD, Task CRUD, status transitions, PostgreSQL-specific queries (add_tmp_node, get_tasks_by_jobs), migration idempotency.
#   DEPENDS: M-DB, M-CONFIG-DB
#   LINKS: M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_add_and_get_node - round-trip add_node + get_node
#   test_get_all_nodes_filtering - get_all_nodes, get_enabled_nodes, get_disabled_nodes
#   test_has_node - existing and non-existing IP
#   test_enable_disable_node - toggling enabled status
#   test_remove_node - node removed after removal
#   test_count_aggregations - count_nodes_clouds, count_nodes_by_status
#   test_add_and_get_task - round-trip add_task + get_task
#   test_task_lifecycle - add → set_running → set_done
#   test_set_task_error - with and without error message
#   test_get_tasks_by_status - filtering across statuses
#   test_get_tasks_by_jobs - array parameter with unnest
#   test_get_task_ids_by_ip_and_status - filtered by IP and status
#   test_get_tasks_with_cloud_by_id_status - JOIN with nodes table
#   test_add_tmp_node - provisional IP, disabled, correct cloud/username
#   test_migrate_idempotency - double migrate succeeds
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial integration tests for DB class.
# END_CHANGE_SUMMARY

"""Integration tests for DB class against real PostgreSQL."""

from yascheduler.db import DB, TaskStatus


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------


# START_CONTRACT: test_add_and_get_node
#   PURPOSE: Verify add_node + get_node round-trip with all fields.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_add_and_get_node
async def test_add_and_get_node(db: DB):
    """Insert a node and retrieve it; verify all fields match."""
    node = await db.add_node(
        "10.0.0.1", "admin", port=2222, ncpus=8, cloud="azure", enabled=True
    )
    assert node.ip == "10.0.0.1"
    assert node.username == "admin"
    assert node.port == 2222
    assert node.ncpus == 8
    assert node.cloud == "azure"
    assert node.enabled is True

    retrieved = await db.get_node("10.0.0.1")
    assert retrieved is not None
    assert retrieved.ip == "10.0.0.1"
    assert retrieved.username == "admin"
    assert retrieved.port == 2222
    assert retrieved.ncpus == 8
    assert retrieved.cloud == "azure"
    assert retrieved.enabled is True


# START_CONTRACT: test_get_all_nodes_filtering
#   PURPOSE: Verify get_all_nodes, get_enabled_nodes, get_disabled_nodes filtering.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_get_all_nodes_filtering
async def test_get_all_nodes_filtering(db: DB):
    """Add enabled and disabled nodes; verify filtered queries."""
    await db.add_node("10.0.0.1", "root", enabled=True)
    await db.add_node("10.0.0.2", "root", enabled=False)

    all_nodes = await db.get_all_nodes()
    assert len(all_nodes) == 2

    enabled = await db.get_enabled_nodes()
    assert len(enabled) == 1
    assert enabled[0].ip == "10.0.0.1"

    disabled = await db.get_disabled_nodes()
    assert len(disabled) == 1
    assert disabled[0].ip == "10.0.0.2"


# START_CONTRACT: test_has_node
#   PURPOSE: Verify has_node returns True for existing IP and False for non-existing.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_has_node
async def test_has_node(db: DB):
    """Check has_node for existing and non-existing IPs."""
    await db.add_node("10.0.0.1", "root")

    assert await db.has_node("10.0.0.1") is True
    assert await db.has_node("10.0.0.99") is False


# START_CONTRACT: test_enable_disable_node
#   PURPOSE: Verify enable_node / disable_node toggle the enabled flag.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_enable_disable_node
async def test_enable_disable_node(db: DB):
    """Toggle node enabled status and verify."""
    await db.add_node("10.0.0.1", "root", enabled=False)

    await db.enable_node("10.0.0.1")
    node = await db.get_node("10.0.0.1")
    assert node is not None
    assert node.enabled is True

    await db.disable_node("10.0.0.1")
    node = await db.get_node("10.0.0.1")
    assert node is not None
    assert node.enabled is False


# START_CONTRACT: test_remove_node
#   PURPOSE: Verify remove_node deletes the node; get_node returns None after removal.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_remove_node
async def test_remove_node(db: DB):
    """Remove a node and verify it is gone."""
    await db.add_node("10.0.0.1", "root")
    assert await db.has_node("10.0.0.1") is True

    await db.remove_node("10.0.0.1")
    assert await db.has_node("10.0.0.1") is False
    assert await db.get_node("10.0.0.1") is None


# START_CONTRACT: test_count_aggregations
#   PURPOSE: Verify count_nodes_clouds and count_nodes_by_status aggregation.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_count_aggregations
async def test_count_aggregations(db: DB):
    """Verify cloud and status aggregation queries."""
    await db.add_node("10.0.0.1", "root", cloud="azure", enabled=True)
    await db.add_node("10.0.0.2", "root", cloud="azure", enabled=False)
    await db.add_node("10.0.0.3", "root", cloud="hetzner", enabled=True)

    clouds = await db.count_nodes_clouds()
    assert clouds == {"azure": 2, "hetzner": 1}

    by_status = await db.count_nodes_by_status()
    assert by_status[True] == 2
    assert by_status[False] == 1


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------


# START_CONTRACT: test_add_and_get_task
#   PURPOSE: Verify add_task + get_task round-trip including metadata.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_add_and_get_task
async def test_add_and_get_task(db: DB):
    """Add a task and retrieve it; verify all fields including metadata."""
    task = await db.add_task(label="calc", ip_addr="10.0.0.1", metadata={"param": 42})
    assert task.task_id >= 1
    assert task.label == "calc"
    assert task.ip == "10.0.0.1"
    assert task.status == TaskStatus.TO_DO
    assert task.metadata == {"param": 42}

    retrieved = await db.get_task(task.task_id)
    assert retrieved is not None
    assert retrieved.task_id == task.task_id
    assert retrieved.label == "calc"
    assert retrieved.ip == "10.0.0.1"
    assert retrieved.status == TaskStatus.TO_DO
    assert retrieved.metadata == {"param": 42}


# START_CONTRACT: test_task_lifecycle
#   PURPOSE: Verify full task lifecycle: add → set_running → set_done with status and IP transitions.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_task_lifecycle
async def test_task_lifecycle(db: DB):
    """Walk a task through TO_DO → RUNNING → DONE and verify each step."""
    task = await db.add_task(label="sim", ip_addr="10.0.0.1")
    assert task.status == TaskStatus.TO_DO

    await db.set_task_running(task.task_id, "10.0.0.5")
    running = await db.get_task(task.task_id)
    assert running is not None
    assert running.status == TaskStatus.RUNNING
    assert running.ip == "10.0.0.5"

    await db.set_task_done(task.task_id, {"result": "ok"})
    done = await db.get_task(task.task_id)
    assert done is not None
    assert done.status == TaskStatus.DONE
    assert done.metadata == {"result": "ok"}


# START_CONTRACT: test_set_task_error
#   PURPOSE: Verify set_task_error behaves correctly with and without error message.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_set_task_error
async def test_set_task_error(db: DB):
    """set_task_error embeds error in metadata; without error passes metadata unchanged."""
    task = await db.add_task(label="fail-job")

    # With error message
    await db.set_task_error(task.task_id, {"key": "val"}, "crash")
    t = await db.get_task(task.task_id)
    assert t is not None
    assert t.status == TaskStatus.DONE
    assert t.metadata == {"key": "val", "error": "crash"}

    # Without error message (use a new task for clarity)
    task2 = await db.add_task(label="fail-job2")
    await db.set_task_error(task2.task_id, {"only": "meta"})
    t2 = await db.get_task(task2.task_id)
    assert t2 is not None
    assert t2.status == TaskStatus.DONE
    assert t2.metadata == {"only": "meta"}


# START_CONTRACT: test_get_tasks_by_status
#   PURPOSE: Verify get_tasks_by_status filters correctly by status values.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_get_tasks_by_status
async def test_get_tasks_by_status(db: DB):
    """Filter tasks by status; multiple statuses supported."""
    await db.add_task(label="todo", status=TaskStatus.TO_DO)
    await db.add_task(label="running", status=TaskStatus.RUNNING)
    await db.add_task(label="done", status=TaskStatus.DONE)

    todo = await db.get_tasks_by_status([TaskStatus.TO_DO])
    assert len(todo) == 1
    assert todo[0].label == "todo"

    running = await db.get_tasks_by_status([TaskStatus.RUNNING])
    assert len(running) == 1
    assert running[0].label == "running"

    done = await db.get_tasks_by_status([TaskStatus.DONE])
    assert len(done) == 1
    assert done[0].label == "done"

    # Multiple statuses
    multi = await db.get_tasks_by_status([TaskStatus.TO_DO, TaskStatus.DONE])
    assert len(multi) == 2


# START_CONTRACT: test_get_tasks_by_jobs
#   PURPOSE: Verify get_tasks_by_jobs uses unnest to filter by task IDs array.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_get_tasks_by_jobs
async def test_get_tasks_by_jobs(db: DB):
    """Retrieve tasks by array of IDs; only requested IDs returned."""
    t1 = await db.add_task(label="a")
    await db.add_task(label="b")
    t3 = await db.add_task(label="c")

    results = await db.get_tasks_by_jobs([t1.task_id, t3.task_id])
    assert len(results) == 2
    ids = {r.task_id for r in results}
    assert ids == {t1.task_id, t3.task_id}


# START_CONTRACT: test_get_task_ids_by_ip_and_status
#   PURPOSE: Verify filtering task IDs by IP address and status.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_get_task_ids_by_ip_and_status
async def test_get_task_ids_by_ip_and_status(db: DB):
    """Filter task IDs by IP and status."""
    ip = "192.168.1.1"
    t1 = await db.add_task(label="x", ip_addr=ip, status=TaskStatus.RUNNING)
    await db.add_task(label="y", ip_addr="10.0.0.1", status=TaskStatus.RUNNING)
    await db.add_task(label="z", ip_addr=ip, status=TaskStatus.DONE)

    ids = await db.get_task_ids_by_ip_and_status(ip, TaskStatus.RUNNING)
    assert ids == [t1.task_id]


# START_CONTRACT: test_get_tasks_with_cloud_by_id_status
#   PURPOSE: Verify JOIN query returns tasks with cloud info from nodes table.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_get_tasks_with_cloud_by_id_status
async def test_get_tasks_with_cloud_by_id_status(db: DB):
    """JOIN tasks with nodes to get cloud attribute."""
    await db.add_node("10.0.0.1", "root", cloud="azure", enabled=True)
    t = await db.add_task(ip_addr="10.0.0.1", status=TaskStatus.RUNNING)
    t2 = await db.add_task(ip_addr="10.0.0.1", status=TaskStatus.DONE)

    result = await db.get_tasks_with_cloud_by_id_status(
        [t.task_id, t2.task_id], TaskStatus.RUNNING
    )
    assert len(result) == 1
    assert result[0].task_id == t.task_id
    assert result[0].cloud == "azure"


# ---------------------------------------------------------------------------
# PostgreSQL-specific features
# ---------------------------------------------------------------------------


# START_CONTRACT: test_add_tmp_node
#   PURPOSE: Verify add_tmp_node generates a provisional IP and inserts a disabled node.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_add_tmp_node
async def test_add_tmp_node(db: DB):
    """add_tmp_node creates a disabled node with provisional IP."""
    ip = await db.add_tmp_node("azure", "root")
    assert ip.startswith("prov")
    assert len(ip) > 4  # "prov" + MD5 fragment

    node = await db.get_node(ip)
    assert node is not None
    assert node.enabled is False
    assert node.cloud == "azure"
    assert node.username == "root"


# START_CONTRACT: test_migrate_idempotency
#   PURPOSE: Verify that migrate() can be called multiple times without error.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_migrate_idempotency
async def test_migrate_idempotency(db: DB):
    """Call migrate() twice; no error, tables remain functional."""
    # First migrate (already ran in db fixture, but call again explicitly)
    await db.migrate()
    # Second migrate should be idempotent
    await db.migrate()

    # Verify tables still work
    await db.add_node("10.0.0.1", "root", enabled=True)
    node = await db.get_node("10.0.0.1")
    assert node is not None
    assert node.ip == "10.0.0.1"
