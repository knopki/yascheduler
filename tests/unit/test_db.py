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
from unittest.mock import AsyncMock, MagicMock

import pytest
from pg8000.native import Connection

from yascheduler.db import DB, NodeModel, TaskModel, TaskStatus
from yascheduler.domain.model import Task, TaskContext
from yascheduler.domain.model import TaskStatus as DomainTaskStatus


class _MockColumn:
    def __init__(self, name: str) -> None:
        self.name = name

    def __getitem__(self, key: str) -> str:
        if key == "name":
            return self.name
        raise KeyError(key)


# mypy: disable-error-code="attr-defined"


# START_CONTRACT: mock_conn
#   PURPOSE: Provide a mocked pg8000.Connection with configurable run() and row_count attributes
#   INPUTS: { None }
#   OUTPUTS: { MagicMock - MagicMock spec'd as Connection with run=MagicMock() }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: mock_conn
@pytest.fixture
def mock_conn() -> MagicMock:
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
async def db(mock_conn: MagicMock) -> DB:
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
async def test_add_node(db: DB, mock_conn: MagicMock) -> None:
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
async def test_get_node_found(db: DB, mock_conn: MagicMock) -> None:
    """returns NodeModel when row found"""
    mock_conn.run.return_value = [("10.0.0.1", 4, True, "az", "root", 22)]
    mock_conn.columns = [
        _MockColumn("ip"),
        _MockColumn("ncpus"),
        _MockColumn("enabled"),
        _MockColumn("cloud"),
        _MockColumn("username"),
        _MockColumn("port"),
    ]
    node = await db.get_node("10.0.0.1")
    assert node is not None
    assert node.ip == "10.0.0.1"
    assert node.ncpus == 4
    call_args = mock_conn.run.call_args
    assert "SELECT" in call_args[0][0]
    assert "ip" in call_args[0][0]
    assert "ncpus" in call_args[0][0]
    assert call_args[1]["ip"] == "10.0.0.1"


# START_CONTRACT: test_get_node_not_found
#   PURPOSE: Verify get_node returns None when mock returns empty/no rows
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_get_node_not_found
async def test_get_node_not_found(db: DB, mock_conn: MagicMock) -> None:
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
async def test_get_all_nodes(db: DB, mock_conn: MagicMock) -> None:
    """returns list of NodeModel from all rows"""
    mock_conn.run.return_value = [
        ("10.0.0.1", 4, True, None, "root", 22),
        ("10.0.0.2", 8, False, "hetzner", "admin", 2222),
    ]
    mock_conn.columns = [
        _MockColumn("ip"),
        _MockColumn("ncpus"),
        _MockColumn("enabled"),
        _MockColumn("cloud"),
        _MockColumn("username"),
        _MockColumn("port"),
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
async def test_enable_node(db: DB, mock_conn: MagicMock) -> None:
    """executes UPDATE SET enabled=TRUE"""
    await db.enable_node("10.0.0.1")
    call_args = mock_conn.run.call_args
    assert "UPDATE yascheduler_nodes" in call_args[0][0]
    assert "enabled = TRUE" in call_args[0][0]
    assert call_args[1]["ip"] == "10.0.0.1"


# START_CONTRACT: test_disable_node
#   PURPOSE: Verify disable_node executes UPDATE SET enabled=FALSE with correct IP
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_disable_node
async def test_disable_node(db: DB, mock_conn: MagicMock) -> None:
    """executes UPDATE SET enabled=FALSE"""
    await db.disable_node("10.0.0.1")
    call_args = mock_conn.run.call_args
    assert "UPDATE yascheduler_nodes" in call_args[0][0]
    assert "enabled = FALSE" in call_args[0][0]
    assert call_args[1]["ip"] == "10.0.0.1"


# START_CONTRACT: test_remove_node
#   PURPOSE: Verify remove_node executes DELETE with correct IP
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_remove_node
async def test_remove_node(db: DB, mock_conn: MagicMock) -> None:
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
async def test_add_task(db: DB, mock_conn: MagicMock) -> None:
    """executes INSERT and returns TaskModel"""
    mock_conn.run.return_value = [(1, "calc", "10.0.0.1", 0, {})]
    mock_conn.columns = [
        _MockColumn("task_id"),
        _MockColumn("label"),
        _MockColumn("ip"),
        _MockColumn("status"),
        _MockColumn("metadata"),
    ]
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
async def test_get_task(db: DB, mock_conn: MagicMock) -> None:
    """executes SELECT and returns TaskModel"""
    mock_conn.run.return_value = [(42, "job", "10.0.0.1", 1, {"k": "v"})]
    mock_conn.columns = [
        _MockColumn("task_id"),
        _MockColumn("label"),
        _MockColumn("ip"),
        _MockColumn("status"),
        _MockColumn("metadata"),
    ]
    task = await db.get_task(42)
    assert task is not None
    assert task.task_id == 42
    assert task.status == TaskStatus.RUNNING
    call_args = mock_conn.run.call_args
    assert "SELECT" in call_args[0][0]
    assert "task_id" in call_args[0][0]
    assert call_args[1]["task_id"] == 42


# START_CONTRACT: test_update_task_status
#   PURPOSE: Verify update_task_status delegates to repo.update_status with correct parameters
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_update_task_status
async def test_update_task_status(db: DB, mock_conn: MagicMock) -> None:
    """delegates to repo.update_status with correct status"""
    from unittest.mock import AsyncMock

    mock_repo = AsyncMock()
    object.__setattr__(db, "_task_repo", mock_repo)

    await db.update_task_status(5, TaskStatus.RUNNING)

    mock_repo.update_status.assert_called_once()
    call_args = mock_repo.update_status.call_args
    assert call_args[0][0] == 5  # task_id
    assert call_args[0][1].value == 1  # TaskStatus.RUNNING


# START_CONTRACT: test_set_task_running
#   PURPOSE: Verify set_task_running updates status to RUNNING and sets IP
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_set_task_running
async def test_set_task_running(db: DB, mock_conn: MagicMock) -> None:
    """updates status to RUNNING and sets IP"""
    mock_task = Task(
        task_id=42,
        label="test",
        context=TaskContext(engine="fleur"),
        status=DomainTaskStatus.TO_DO,
    )
    object.__setattr__(db, "_task_repo", AsyncMock())
    db._task_repo.get.return_value = mock_task

    await db.set_task_running(42, "10.0.0.1")

    db._task_repo.get.assert_called_once_with(42)
    saved_task = db._task_repo.save.call_args[0][0]
    assert saved_task.status == DomainTaskStatus.RUNNING
    assert saved_task.allocated_ip == "10.0.0.1"


# START_CONTRACT: test_set_task_done
#   PURPOSE: Verify set_task_done updates status to DONE and sets metadata
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_set_task_done
async def test_set_task_done(db: DB, mock_conn: MagicMock) -> None:
    """updates status to DONE and sets metadata"""
    meta = {"result": "ok"}
    mock_task = Task(
        task_id=42,
        label="test",
        context=TaskContext(engine="fleur"),
        status=DomainTaskStatus.RUNNING,
    )
    object.__setattr__(db, "_task_repo", AsyncMock())
    db._task_repo.get.return_value = mock_task

    await db.set_task_done(42, meta)

    db._task_repo.get.assert_called_once_with(42)
    saved_task = db._task_repo.save.call_args[0][0]
    assert saved_task.status == DomainTaskStatus.DONE
    assert saved_task.context.extra["result"] == "ok"


# START_CONTRACT: test_set_task_error_with_message
#   PURPOSE: Verify set_task_error embeds error key in metadata when error message provided
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_set_task_error_with_message
async def test_set_task_error_with_message(db: DB, mock_conn: MagicMock) -> None:
    """embeds error in metadata when message provided"""
    meta = {"key": "val"}
    mock_task = Task(
        task_id=42,
        label="test",
        context=TaskContext(engine="fleur"),
        status=DomainTaskStatus.RUNNING,
    )
    object.__setattr__(db, "_task_repo", AsyncMock())
    db._task_repo.get.return_value = mock_task

    await db.set_task_error(42, meta, "crash")

    db._task_repo.get.assert_called_once_with(42)
    saved_task = db._task_repo.save.call_args[0][0]
    assert saved_task.status == DomainTaskStatus.DONE
    assert saved_task.context.extra["key"] == "val"
    assert saved_task.context.error == "crash"


# START_CONTRACT: test_set_task_error_without_message
#   PURPOSE: Verify set_task_error passes metadata unchanged when no error message
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DB]
# END_CONTRACT: test_set_task_error_without_message
async def test_set_task_error_without_message(db: DB, mock_conn: MagicMock) -> None:
    """passes metadata unchanged when no error message"""
    meta = {"key": "val"}
    mock_task = Task(
        task_id=42,
        label="test",
        context=TaskContext(engine="fleur"),
        status=DomainTaskStatus.RUNNING,
    )
    object.__setattr__(db, "_task_repo", AsyncMock())
    db._task_repo.get.return_value = mock_task

    await db.set_task_error(42, meta)

    db._task_repo.get.assert_called_once_with(42)
    saved_task = db._task_repo.save.call_args[0][0]
    assert saved_task.status == DomainTaskStatus.DONE
    assert saved_task.context.extra["key"] == "val"
    assert saved_task.context.error is None
