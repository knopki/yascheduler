# FILE: tests/unit/test_fake_db.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for FakeDB covering task/node CRUD, auto-increment, status transitions.
#   SCOPE: add_task/get_task, add_node/get_all_nodes, status transitions, enable/disable/remove, error handling.
#   DEPENDS: M-DB (via tests/fixtures/fake_db.py)
#   LINKS: M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   fake_db - fixture returning a fresh FakeDB instance
#   test_fake_db_add_get_task - add_task/get_task roundtrip with auto-increment
#   test_fake_db_add_task_increments_id - each add_task gets incremented ID
#   test_fake_db_add_get_all_nodes - add_node/get_all_nodes roundtrip
#   test_fake_db_status_transitions - RUNNING -> DONE transition
#   test_fake_db_get_node_none - get_node returns None for unknown IP
#   test_fake_db_get_task_none - get_task returns None for unknown ID
#   test_fake_db_enable_disable_node - enable/disable toggle
#   test_fake_db_remove_node - remove_node deletes
#   test_fake_db_set_task_error - embeds error in metadata
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial FakeDB unit tests
# END_CHANGE_SUMMARY

import pytest

from tests.fixtures.fake_db import FakeDB
from yascheduler.db import NodeModel, TaskStatus

# mypy: disable-error-code="attr-defined"


# START_CONTRACT: fake_db
#   PURPOSE: Provide a fresh FakeDB instance for each test
#   INPUTS: { None }
#   OUTPUTS: { FakeDB - newly initialized in-memory DB double }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: fake_db
@pytest.fixture
async def fake_db():
    return FakeDB()


# START_CONTRACT: test_fake_db_add_get_task
#   PURPOSE: Verify add_task creates auto-incremented task and get_task retrieves it
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_add_get_task
async def test_fake_db_add_get_task(fake_db) -> None:
    """add_task then get_task returns TaskModel with auto-incremented ID"""
    task = await fake_db.add_task(label="test")
    assert task.task_id == 1
    assert task.label == "test"
    assert task.status == TaskStatus.TO_DO

    retrieved = await fake_db.get_task(1)
    assert retrieved is not None
    assert retrieved.task_id == 1
    assert retrieved.label == "test"


# START_CONTRACT: test_fake_db_add_task_increments_id
#   PURPOSE: Verify each add_task gets an incremented task_id
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_add_task_increments_id
async def test_fake_db_add_task_increments_id(fake_db) -> None:
    """each add_task gets an incremented task_id"""
    t1 = await fake_db.add_task(label="a")
    t2 = await fake_db.add_task(label="b")
    assert t1.task_id == 1
    assert t2.task_id == 2


# START_CONTRACT: test_fake_db_add_get_all_nodes
#   PURPOSE: Verify add_node stores nodes and get_all_nodes returns all as NodeModel
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_add_get_all_nodes
async def test_fake_db_add_get_all_nodes(fake_db) -> None:
    """add_node stores nodes, get_all_nodes returns all"""
    n1 = await fake_db.add_node("10.0.0.1", "root")
    n2 = await fake_db.add_node("10.0.0.2", "admin", port=2222)
    assert n1.ip == "10.0.0.1"
    assert n2.port == 2222

    nodes = await fake_db.get_all_nodes()
    assert len(nodes) == 2
    assert isinstance(nodes[0], NodeModel)
    assert nodes[1].port == 2222


# START_CONTRACT: test_fake_db_status_transitions
#   PURPOSE: Verify set_task_running, set_task_done update task status correctly
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_status_transitions
async def test_fake_db_status_transitions(fake_db) -> None:
    """task status transitions through RUNNING to DONE"""
    await fake_db.add_task(label="job")

    await fake_db.set_task_running(1, "10.0.0.1")
    task = await fake_db.get_task(1)
    assert task.status == TaskStatus.RUNNING
    assert task.ip == "10.0.0.1"

    await fake_db.set_task_done(1, {"result": "ok"})
    task = await fake_db.get_task(1)
    assert task.status == TaskStatus.DONE
    assert task.metadata == {"result": "ok"}


# START_CONTRACT: test_fake_db_get_node_none
#   PURPOSE: Verify get_node returns None for unknown IP
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_get_node_none
async def test_fake_db_get_node_none(fake_db) -> None:
    """returns None for unknown IP"""
    assert await fake_db.get_node("unknown") is None


# START_CONTRACT: test_fake_db_get_task_none
#   PURPOSE: Verify get_task returns None for unknown task_id
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_get_task_none
async def test_fake_db_get_task_none(fake_db) -> None:
    """returns None for unknown task_id"""
    assert await fake_db.get_task(999) is None


# START_CONTRACT: test_fake_db_enable_disable_node
#   PURPOSE: Verify enable_node and disable_node toggle the enabled flag
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_enable_disable_node
async def test_fake_db_enable_disable_node(fake_db) -> None:
    """enable_node and disable_node toggle enabled flag"""
    await fake_db.add_node("10.0.0.1", "root", enabled=False)
    node = await fake_db.get_node("10.0.0.1")
    assert node.enabled is False

    await fake_db.enable_node("10.0.0.1")
    node = await fake_db.get_node("10.0.0.1")
    assert node.enabled is True

    await fake_db.disable_node("10.0.0.1")
    node = await fake_db.get_node("10.0.0.1")
    assert node.enabled is False


# START_CONTRACT: test_fake_db_remove_node
#   PURPOSE: Verify remove_node deletes the node
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_remove_node
async def test_fake_db_remove_node(fake_db) -> None:
    """remove_node deletes the node"""
    await fake_db.add_node("10.0.0.1", "root")
    await fake_db.remove_node("10.0.0.1")
    assert await fake_db.get_node("10.0.0.1") is None


# START_CONTRACT: test_fake_db_set_task_error
#   PURPOSE: Verify set_task_error embeds error in metadata and sets DONE
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_fake_db_set_task_error
async def test_fake_db_set_task_error(fake_db) -> None:
    """embeds error in metadata and marks DONE"""
    await fake_db.add_task(label="job")
    await fake_db.set_task_error(1, {"key": "val"}, "oops")
    task = await fake_db.get_task(1)
    assert task.status == TaskStatus.DONE
    assert task.metadata == {"key": "val", "error": "oops"}
