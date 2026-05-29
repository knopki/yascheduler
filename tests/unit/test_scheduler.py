# FILE: tests/unit/test_scheduler.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for Scheduler class with mocked DB, clouds, and remote machines.
#   SCOPE: Queue configuration (__attrs_post_init__), create_new_task validation and success path, allocate_task free/cloud/error paths, clouds_get_capacity, WebhookPayload construction.
#   DEPENDS: M-SCHEDULER
#   LINKS: M-SCHEDULER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_scheduler_queues_configured - Queue names and maxsizes match config
#   test_create_new_task_unknown_engine - RuntimeError for unknown engine
#   test_create_new_task_missing_input_file - RuntimeError for missing input file
#   test_create_new_task_success - db.add_task, update_task_meta, commit, TaskModel returned
#   test_allocate_task_free_machine - Free machine found, set_task_running, mark_task_done
#   test_allocate_task_no_free_machine - No free machine, clouds.allocate called
#   test_allocate_task_unsupported_engine - Unsupported engine, set_task_error
#   test_clouds_get_capacity_available - Positive capacity when max > current
#   test_clouds_get_capacity_over_capacity - Returns 0 when current exceeds max
#   TestWebhookPayload - WebhookPayload dataclass construction and defaults
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial Scheduler unit tests with mocked dependencies.
# END_CHANGE_SUMMARY
#
"""Unit tests for Scheduler class - queue config, create_new_task, allocate_task, clouds_get_capacity, WebhookPayload."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.scheduler import Scheduler, WebhookPayload
from yascheduler.db import TaskModel, TaskStatus
from yascheduler.remote_machine.remote_machine_repository import RemoteMachineRepository
from tests.fixtures.mock_scheduler import create_test_config, make_scheduler
from tests.fixtures.mock_clouds import make_mock_clouds
from tests.fixtures.mock_remote_machine import make_mock_remote_machine

TEST_INI = """
[local]
conn_machine_pending = 10
allocate_pending = 5
consume_pending = 3
deallocate_pending = 2
webhook_reqs_limit = 3

[remote]
tasks_dir = /tmp/yascheduler/tasks
data_dir = /tmp/yascheduler/data

[engine.test_engine]
spawn = echo hello
check_cmd = echo ok
input_files = input.txt
output_files = output.txt
platforms = linux
"""


# START_CONTRACT: test_config
#   PURPOSE: Create test config from TEST_INI string
#   INPUTS: { None }
#   OUTPUTS: { SchedulerConfig - parsed test configuration }
# END_CONTRACT: test_config
@pytest.fixture
def test_config():
    return create_test_config(TEST_INI)


# START_CONTRACT: mock_db
#   PURPOSE: Create a MagicMock DB with AsyncMock methods for Scheduler
#   INPUTS: { None }
#   OUTPUTS: { MagicMock - mock database with add_task, update_task_meta, commit, get_tasks_by_status, set_task_running, set_task_error as AsyncMock methods }
# END_CONTRACT: mock_db
@pytest.fixture
def mock_db():
    """Create a mock DB with all methods needed by Scheduler"""
    db = MagicMock()
    db.add_task = AsyncMock()
    db.update_task_meta = AsyncMock()
    db.commit = AsyncMock()
    db.get_tasks_by_status = AsyncMock(return_value=[])
    db.set_task_running = AsyncMock()
    db.set_task_error = AsyncMock()
    return db


# START_CONTRACT: mock_clouds
#   PURPOSE: Create mock clouds provider with default max_nodes=10, current_nodes=5
#   INPUTS: { None }
#   OUTPUTS: { MockCloudProvider - mock cloud provider with allocate, mark_task_done, get_capacity methods }
# END_CONTRACT: mock_clouds
@pytest.fixture
def mock_clouds():
    return make_mock_clouds()


# START_CONTRACT: empty_remote_machines
#   PURPOSE: Create empty RemoteMachineRepository with no machines
#   INPUTS: { None }
#   OUTPUTS: { RemoteMachineRepository - empty repository with MagicMock log }
# END_CONTRACT: empty_remote_machines
@pytest.fixture
def empty_remote_machines():
    return RemoteMachineRepository(log=MagicMock())


# START_CONTRACT: mock_remote_machines
#   PURPOSE: Create RemoteMachineRepository with one free linux machine at 10.0.0.1
#   INPUTS: { None }
#   OUTPUTS: { RemoteMachineRepository - repository containing one free linux machine }
# END_CONTRACT: mock_remote_machines
@pytest.fixture
def mock_remote_machines():
    """RemoteMachineRepository with one free linux machine"""
    repo = RemoteMachineRepository(log=MagicMock())
    machine = make_mock_remote_machine(ip="10.0.0.1", platforms=["linux"], busy=False)
    repo.data["10.0.0.1"] = machine
    return repo


# START_CONTRACT: test_scheduler_queues_configured
#   PURPOSE: Verify Scheduler.__attrs_post_init__ creates queues with correct names and maxsizes from config
#   INPUTS: { test_config, mock_db, mock_clouds, empty_remote_machines - pytest fixtures }
#   OUTPUTS: { None - test assertions on queue names and maxsizes }
# END_CONTRACT: test_scheduler_queues_configured
@pytest.mark.asyncio
async def test_scheduler_queues_configured(
    test_config, mock_db, mock_clouds, empty_remote_machines
):
    """Scheduler.__attrs_post_init__ creates queues with correct names and maxsizes"""
    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=mock_clouds,
        remote_machines=empty_remote_machines,
    )
    assert scheduler.conn_machine_q.name == "conn_machine"
    assert scheduler.conn_machine_q.maxsize == 10
    assert scheduler.allocate_q.name == "allocate"
    assert scheduler.allocate_q.maxsize == 5
    assert scheduler.consume_q.name == "consume"
    assert scheduler.consume_q.maxsize == 3
    assert scheduler.deallocate_q.name == "deallocate"
    assert scheduler.deallocate_q.maxsize == 2


# START_CONTRACT: test_create_new_task_unknown_engine
#   PURPOSE: Verify RuntimeError is raised when engine_name does not exist in config
#   INPUTS: { test_config, mock_db, mock_clouds, empty_remote_machines - pytest fixtures }
#   OUTPUTS: { None - test assertions via pytest.raises }
# END_CONTRACT: test_create_new_task_unknown_engine
@pytest.mark.asyncio
async def test_create_new_task_unknown_engine(
    test_config, mock_db, mock_clouds, empty_remote_machines
):
    """create_new_task raises RuntimeError for unknown engine"""
    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=mock_clouds,
        remote_machines=empty_remote_machines,
    )
    with pytest.raises(RuntimeError, match="nonexistent"):
        await scheduler.create_new_task(
            label="test",
            metadata={"input.txt": "/tmp/input.txt"},
            engine_name="nonexistent",
        )


# START_CONTRACT: test_create_new_task_missing_input_file
#   PURPOSE: Verify RuntimeError is raised when required input file is missing from metadata
#   INPUTS: { test_config, mock_db, mock_clouds, empty_remote_machines - pytest fixtures }
#   OUTPUTS: { None - test assertions via pytest.raises }
# END_CONTRACT: test_create_new_task_missing_input_file
@pytest.mark.asyncio
async def test_create_new_task_missing_input_file(
    test_config, mock_db, mock_clouds, empty_remote_machines
):
    """create_new_task raises RuntimeError when input file is missing from metadata"""
    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=mock_clouds,
        remote_machines=empty_remote_machines,
    )
    with pytest.raises(RuntimeError, match="input.txt"):
        await scheduler.create_new_task(
            label="test",
            metadata={},  # missing input.txt
            engine_name="test_engine",
        )


# START_CONTRACT: test_create_new_task_success
#   PURPOSE: Verify full success path: db.add_task, db.update_task_meta, db.commit called and TaskModel returned
#   INPUTS: { test_config, mock_db, mock_clouds, empty_remote_machines - pytest fixtures }
#   OUTPUTS: { None - test assertions on mock calls and returned TaskModel }
# END_CONTRACT: test_create_new_task_success
@pytest.mark.asyncio
async def test_create_new_task_success(
    test_config, mock_db, mock_clouds, empty_remote_machines
):
    """create_new_task calls db.add_task, db.update_task_meta, db.commit, returns TaskModel"""
    expected_task = TaskModel(
        task_id=1, label="test", ip="", status=TaskStatus.TO_DO, metadata={}
    )
    mock_db.add_task.return_value = expected_task

    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=mock_clouds,
        remote_machines=empty_remote_machines,
    )
    result = await scheduler.create_new_task(
        label="test",
        metadata={"input.txt": "/tmp/input.txt"},
        engine_name="test_engine",
    )

    mock_db.add_task.assert_called_once()
    call_args = mock_db.add_task.call_args
    # label is the first positional argument
    assert call_args[0][0] == "test"
    assert call_args[1]["status"] == TaskStatus.TO_DO
    # Verify metadata contains engine key
    metadata_arg = call_args[1]["metadata"]
    assert metadata_arg["engine"] == "test_engine"
    assert "input.txt" in metadata_arg

    # Verify db.update_task_meta was called with remote_folder
    mock_db.update_task_meta.assert_called_once()
    meta_call_args = mock_db.update_task_meta.call_args
    assert meta_call_args[0][0] == 1  # task_id
    assert "remote_folder" in meta_call_args[0][1]

    # Verify commit was called
    mock_db.commit.assert_called_once()

    # Verify returned task
    assert result == expected_task


# START_CONTRACT: test_allocate_task_free_machine
#   PURPOSE: Verify allocate_task finds free machine, calls set_task_running and mark_task_done
#   INPUTS: { test_config, mock_db, mock_clouds, mock_remote_machines - pytest fixtures; monkeypatch }
#   OUTPUTS: { None - test assertions on True result and mock calls }
# END_CONTRACT: test_allocate_task_free_machine
@pytest.mark.asyncio
@patch.object(Scheduler, "start_task_on_machine", new=AsyncMock(return_value=True))
@patch.object(Scheduler, "do_task_webhook", new=AsyncMock())
async def test_allocate_task_free_machine(
    test_config, mock_db, mock_clouds, mock_remote_machines, monkeypatch
):
    """allocate_task finds free machine, calls db.set_task_running and clouds.mark_task_done"""
    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=mock_clouds,
        remote_machines=mock_remote_machines,
    )

    machine = mock_remote_machines.data["10.0.0.1"]
    monkeypatch.setattr(machine, "start_occupancy_check", AsyncMock())

    task = TaskModel(
        task_id=1,
        label="test",
        ip="",
        status=TaskStatus.TO_DO,
        metadata={
            "engine": "test_engine",
            "remote_folder": "/tmp/tasks/20240101_000000_1",
        },
    )

    result = await scheduler.allocate_task(task)

    assert result is True
    mock_db.set_task_running.assert_called_once_with(1, "10.0.0.1")
    mock_db.commit.assert_called_once()
    mock_clouds.mark_task_done.assert_called_once_with(1)


# START_CONTRACT: test_allocate_task_no_free_machine
#   PURPOSE: Verify allocate_task calls clouds.allocate when no free machine, returns False
#   INPUTS: { test_config, mock_db, mock_clouds, empty_remote_machines - pytest fixtures }
#   OUTPUTS: { None - test assertions on False result and clouds.allocate call }
# END_CONTRACT: test_allocate_task_no_free_machine
@pytest.mark.asyncio
@patch.object(Scheduler, "do_task_webhook", new=AsyncMock())
async def test_allocate_task_no_free_machine(
    test_config, mock_db, mock_clouds, empty_remote_machines
):
    """allocate_task calls clouds.allocate when no free machine, returns False"""
    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=mock_clouds,
        remote_machines=empty_remote_machines,
    )

    task = TaskModel(
        task_id=1,
        label="test",
        ip="",
        status=TaskStatus.TO_DO,
        metadata={"engine": "test_engine", "remote_folder": "/tmp/tasks/dir"},
    )

    result = await scheduler.allocate_task(task)

    assert result is False
    mock_clouds.allocate.assert_called_once()
    call_args = mock_clouds.allocate.call_args
    assert call_args[1]["want_platforms"] == ("linux",)


# START_CONTRACT: test_allocate_task_unsupported_engine
#   PURPOSE: Verify allocate_task sets task error when engine not in config
#   INPUTS: { test_config, mock_db, mock_clouds, empty_remote_machines - pytest fixtures }
#   OUTPUTS: { None - test assertions on False result and db.set_task_error call }
# END_CONTRACT: test_allocate_task_unsupported_engine
@pytest.mark.asyncio
@patch.object(Scheduler, "do_task_webhook", new=AsyncMock())
async def test_allocate_task_unsupported_engine(
    test_config, mock_db, mock_clouds, empty_remote_machines
):
    """allocate_task sets task error when engine not in config"""
    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=mock_clouds,
        remote_machines=empty_remote_machines,
    )

    task = TaskModel(
        task_id=1,
        label="test",
        ip="",
        status=TaskStatus.TO_DO,
        metadata={"engine": "nonexistent"},
    )

    result = await scheduler.allocate_task(task)

    assert result is False
    mock_db.set_task_error.assert_called_once()
    call_args = mock_db.set_task_error.call_args
    assert "unsupported engine" in str(call_args[1]["error"]).lower()


# START_CONTRACT: test_clouds_get_capacity_available
#   PURPOSE: Verify clouds_get_capacity returns positive capacity when max_nodes > current_nodes
#   INPUTS: { test_config, mock_db, mock_clouds, empty_remote_machines - pytest fixtures }
#   OUTPUTS: { None - test assertion on returned capacity value }
# END_CONTRACT: test_clouds_get_capacity_available
@pytest.mark.asyncio
async def test_clouds_get_capacity_available(
    test_config, mock_db, mock_clouds, empty_remote_machines
):
    """clouds_get_capacity returns positive capacity when max > current"""
    # mock_clouds defaults: max_nodes=10, current_nodes=5
    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=mock_clouds,
        remote_machines=empty_remote_machines,
    )
    result = await scheduler.clouds_get_capacity()
    assert result == 5  # 10 - 5


# START_CONTRACT: test_clouds_get_capacity_over_capacity
#   PURPOSE: Verify clouds_get_capacity returns 0 when current_nodes exceeds max_nodes
#   INPUTS: { test_config, mock_db, empty_remote_machines - pytest fixtures }
#   OUTPUTS: { None - test assertion on returned zero capacity }
# END_CONTRACT: test_clouds_get_capacity_over_capacity
@pytest.mark.asyncio
async def test_clouds_get_capacity_over_capacity(
    test_config, mock_db, empty_remote_machines
):
    """clouds_get_capacity returns 0 when current exceeds max"""
    clouds = make_mock_clouds(max_nodes=10, current_nodes=12)
    scheduler = make_scheduler(
        db=mock_db,
        config=test_config,
        clouds=clouds,
        remote_machines=empty_remote_machines,
    )
    result = await scheduler.clouds_get_capacity()
    assert result == 0


class TestWebhookPayload:
    """Tests for WebhookPayload dataclass"""

    # START_CONTRACT: test_construction
    #   PURPOSE: Verify WebhookPayload construction with explicit custom_params
    #   INPUTS: { None }
    #   OUTPUTS: { None - assertions on task_id, status, custom_params fields }
    # END_CONTRACT: test_construction

    def test_construction(self):
        payload = WebhookPayload(task_id=1, status=0, custom_params={"k": "v"})
        assert payload.task_id == 1
        assert payload.status == 0
        assert payload.custom_params == {"k": "v"}

    # START_CONTRACT: test_default_custom_params
    #   PURPOSE: Verify WebhookPayload default custom_params is empty dict when not provided
    #   INPUTS: { None }
    #   OUTPUTS: { None - assertion on default custom_params value }
    # END_CONTRACT: test_default_custom_params

    def test_default_custom_params(self):
        payload = WebhookPayload(task_id=42, status=1)
        assert payload.custom_params == {}
