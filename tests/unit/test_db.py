# FILE: tests/unit/test_db.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for DB class with mocked pg8000.Connection, verifying SQL queries and result mapping.
#   SCOPE: Node CRUD (add, get, get_all, enable, disable, remove) and Task CRUD (add, get, update_status, set_running, set_done, set_error).
#   DEPENDS: M-DB
#   LINKS: M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   mock_conn - fixture: mocked pg8000.Connection
#   db - fixture: DB instance with mock connection and real loop/executor
#   test_add_node - INSERT -> NodeModel
#   test_get_node_found - SELECT returns NodeModel
#   test_get_node_not_found - empty rows -> None
#   test_get_all_nodes - all rows -> NodeModel list
#   test_enable_node - UPDATE enabled=TRUE
#   test_disable_node - UPDATE enabled=FALSE
#   test_remove_node - DELETE by IP
#   test_add_task - INSERT -> TaskModel
#   test_get_task - SELECT -> TaskModel
#   test_update_task_status - UPDATE status value
#   test_set_task_running - UPDATE status=1 + ip
#   test_set_task_done - UPDATE status=2 + metadata
#   test_set_task_error_with_message - embeds error in metadata
#   test_set_task_error_without_message - passes metadata unchanged
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial DB unit tests with mocked connection
# END_CHANGE_SUMMARY

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from pg8000.native import Connection

from yascheduler.db import DB, NodeModel, TaskModel, TaskStatus

# mypy: disable-error-code="attr-defined"


# START_CONTRACT: mock_conn
#   PURPOSE: Provide a mocked pg8000.Connection with configurable run() and row_count attributes
#   INPUTS: { None }
#   OUTPUTS: { MagicMock - MagicMock spec'd as Connection with run=MagicMock() }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: mock_conn
@pytest.fixture
def mock_conn():
    """Mocked pg8000.Connection with configurable run/row_count."""
    conn = MagicMock(spec=Connection)
    conn.run = MagicMock()
    conn.row_count = 0
    return conn


# START_CONTRACT: db
#   PURPOSE: Provide a DB instance wired to a mocked Connection with real asyncio loop and ThreadPoolExecutor
#   INPUTS: { mock_conn: MagicMock - mocked pg8000.Connection from mock_conn fixture }
#   OUTPUTS: { DB - DB instance with mocked connection }
#   SIDE_EFFECTS: Creates ThreadPoolExecutor (not explicitly cleaned up)
#   LINKS: [M-DB]
# END_CONTRACT: db
@pytest.fixture
async def db(mock_conn):
    """DB instance with mocked connection, real loop/executor."""
    loop = asyncio.get_running_loop()
    exe = ThreadPoolExecutor(max_workers=1)
    return DB(loop=loop, executor=exe, conn=mock_conn)


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------


# START_CONTRACT: test_add_node
#   PURPOSE: Verify add_node executes INSERT and returns NodeModel with correct fields
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_add_node
async def test_add_node(db, mock_conn):
    """executes INSERT SQL and returns NodeModel"""
    mock_conn.row_count = 1
    node = await db.add_node("10.0.0.1", "root")
    call_args = mock_conn.run.call_args
    assert "INSERT INTO yascheduler_nodes" in call_args[0][0]
    assert call_args[1]["ip"] == "10.0.0.1"
    assert call_args[1]["username"] == "root"
    assert isinstance(node, NodeModel)
    assert node.ip == "10.0.0.1"


# START_CONTRACT: test_get_node_found
#   PURPOSE: Verify get_node returns NodeModel when mock returns matching row
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_get_node_found
async def test_get_node_found(db, mock_conn):
    """returns NodeModel when row found"""
    mock_conn.run.return_value = [("10.0.0.1", 4, True, "az", "root", 22)]
    node = await db.get_node("10.0.0.1")
    assert node is not None
    assert node.ip == "10.0.0.1"
    assert node.ncpus == 4
    call_args = mock_conn.run.call_args
    assert "SELECT ip, ncpus" in call_args[0][0]
    assert call_args[1]["ip"] == "10.0.0.1"


# START_CONTRACT: test_get_node_not_found
#   PURPOSE: Verify get_node returns None when mock returns empty/no rows
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_get_node_not_found
async def test_get_node_not_found(db, mock_conn):
    """returns None when no matching row"""
    mock_conn.run.return_value = []
    node = await db.get_node("10.0.0.99")
    assert node is None


# START_CONTRACT: test_get_all_nodes
#   PURPOSE: Verify get_all_nodes returns list of NodeModel from all rows
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_get_all_nodes
async def test_get_all_nodes(db, mock_conn):
    """returns list of NodeModel from all rows"""
    mock_conn.run.return_value = [
        ("10.0.0.1", 4, True, None, "root", 22),
        ("10.0.0.2", 8, False, "hetzner", "admin", 2222),
    ]
    nodes = await db.get_all_nodes()
    assert len(nodes) == 2
    assert nodes[0].ip == "10.0.0.1"
    assert nodes[1].ip == "10.0.0.2"


# START_CONTRACT: test_enable_node
#   PURPOSE: Verify enable_node executes UPDATE SET enabled=TRUE with correct IP
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_enable_node
async def test_enable_node(db, mock_conn):
    """executes UPDATE SET enabled=TRUE"""
    await db.enable_node("10.0.0.1")
    call_args = mock_conn.run.call_args
    assert "UPDATE yascheduler_nodes" in call_args[0][0]
    assert "enabled=TRUE" in call_args[0][0]
    assert call_args[1]["ip"] == "10.0.0.1"


# START_CONTRACT: test_disable_node
#   PURPOSE: Verify disable_node executes UPDATE SET enabled=FALSE with correct IP
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_disable_node
async def test_disable_node(db, mock_conn):
    """executes UPDATE SET enabled=FALSE"""
    await db.disable_node("10.0.0.1")
    call_args = mock_conn.run.call_args
    assert "UPDATE yascheduler_nodes" in call_args[0][0]
    assert "enabled=FALSE" in call_args[0][0]
    assert call_args[1]["ip"] == "10.0.0.1"


# START_CONTRACT: test_remove_node
#   PURPOSE: Verify remove_node executes DELETE with correct IP
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_remove_node
async def test_remove_node(db, mock_conn):
    """executes DELETE with correct IP"""
    await db.remove_node("10.0.0.1")
    call_args = mock_conn.run.call_args
    assert "DELETE FROM yascheduler_nodes" in call_args[0][0]
    assert call_args[1]["ip"] == "10.0.0.1"


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------


# START_CONTRACT: test_add_task
#   PURPOSE: Verify add_task executes INSERT and returns TaskModel with generated ID
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_add_task
async def test_add_task(db, mock_conn):
    """executes INSERT and returns TaskModel"""
    mock_conn.run.return_value = [(1, "calc", "10.0.0.1", 0, {})]
    task = await db.add_task(label="calc", ip_addr="10.0.0.1")
    call_args = mock_conn.run.call_args
    assert "INSERT INTO yascheduler_tasks" in call_args[0][0]
    assert call_args[1]["label"] == "calc"
    assert call_args[1]["ip"] == "10.0.0.1"
    assert isinstance(task, TaskModel)
    assert task.task_id == 1
    assert task.label == "calc"


# START_CONTRACT: test_get_task
#   PURPOSE: Verify get_task executes SELECT and maps result to TaskModel
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_get_task
async def test_get_task(db, mock_conn):
    """executes SELECT and returns TaskModel"""
    mock_conn.run.return_value = [(42, "job", "10.0.0.1", 1, {"k": "v"})]
    task = await db.get_task(42)
    assert task is not None
    assert task.task_id == 42
    assert task.status == TaskStatus.RUNNING
    call_args = mock_conn.run.call_args
    assert "SELECT task_id" in call_args[0][0]
    assert call_args[1]["task_id"] == 42


# START_CONTRACT: test_update_task_status
#   PURPOSE: Verify update_task_status executes UPDATE with correct status value
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_update_task_status
async def test_update_task_status(db, mock_conn):
    """executes UPDATE with correct status value"""
    await db.update_task_status(5, TaskStatus.RUNNING)
    call_args = mock_conn.run.call_args
    assert "UPDATE yascheduler_tasks" in call_args[0][0]
    assert call_args[1]["task_id"] == 5
    assert call_args[1]["status"] == 1  # TaskStatus.RUNNING.value


# START_CONTRACT: test_set_task_running
#   PURPOSE: Verify set_task_running updates status to RUNNING and sets IP
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_set_task_running
async def test_set_task_running(db, mock_conn):
    """updates status to RUNNING and sets IP"""
    await db.set_task_running(42, "10.0.0.1")
    call_args = mock_conn.run.call_args
    assert "status=:status" in call_args[0][0]
    assert "ip=:ip" in call_args[0][0]
    assert call_args[1]["status"] == 1  # RUNNING
    assert call_args[1]["ip"] == "10.0.0.1"
    assert call_args[1]["task_id"] == 42


# START_CONTRACT: test_set_task_done
#   PURPOSE: Verify set_task_done updates status to DONE and sets metadata
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_set_task_done
async def test_set_task_done(db, mock_conn):
    """updates status to DONE and sets metadata"""
    meta = {"result": "ok"}
    await db.set_task_done(42, meta)
    call_args = mock_conn.run.call_args
    assert call_args[1]["status"] == 2  # DONE
    assert call_args[1]["metadata"] == meta
    assert call_args[1]["task_id"] == 42


# START_CONTRACT: test_set_task_error_with_message
#   PURPOSE: Verify set_task_error embeds error key in metadata when error message provided
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_set_task_error_with_message
async def test_set_task_error_with_message(db, mock_conn):
    """embeds error in metadata when message provided"""
    meta = {"key": "val"}
    await db.set_task_error(42, meta, "crash")
    call_args = mock_conn.run.call_args
    assert call_args[1]["status"] == 2  # DONE
    assert call_args[1]["metadata"] == {"key": "val", "error": "crash"}
    assert call_args[1]["task_id"] == 42


# START_CONTRACT: test_set_task_error_without_message
#   PURPOSE: Verify set_task_error passes metadata unchanged when no error message
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_set_task_error_without_message
async def test_set_task_error_without_message(db, mock_conn):
    """passes metadata unchanged when no error message"""
    meta = {"key": "val"}
    await db.set_task_error(42, meta)
    call_args = mock_conn.run.call_args
    assert call_args[1]["metadata"] == meta
    assert "error" not in call_args[1]["metadata"]
