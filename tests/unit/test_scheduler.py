# FILE: tests/unit/test_scheduler.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for Scheduler class after refactoring (thin wrapper).
#   SCOPE: create_new_task validation, WebhookPayload construction. Queue/allocate/capacity tests moved to orchestrator/use-case test files.
#   DEPENDS: M-SCHEDULER, M-APPLICATION-SUBMIT
#   LINKS: M-SCHEDULER, M-APPLICATION-SUBMIT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_create_new_task_unknown_engine - Domain UnsupportedEngineError propagates from submit_task use case
#   test_create_new_task_missing_input_file - Domain MissingInputFileError propagates from submit_task use case
#   test_create_new_task_success - submit_task returns task_id and get_task returns TaskModel
#   TestWebhookPayload - WebhookPayload dataclass construction and defaults
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Update tests for refactored Scheduler v2.0.0; skip removed functionality; patch submit_task.
#   PREVIOUS_CHANGE: v1.0.0 - Initial Scheduler unit tests with mocked dependencies.
# END_CHANGE_SUMMARY
#
"""Unit tests for Scheduler class — create_new_task delegation and WebhookPayload."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fixtures.mock_clouds import make_mock_clouds
from tests.fixtures.mock_scheduler import create_test_config, make_scheduler
from yascheduler.db import TaskModel, TaskStatus
from yascheduler.scheduler import WebhookPayload

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


# START_CONTRACT: test_create_new_task_unknown_engine
#   PURPOSE: Verify domain UnsupportedEngineError propagates from submit_task use case
#   INPUTS: { test_config, mock_db, mock_clouds - pytest fixtures }
#   OUTPUTS: { None - test assertions via pytest.raises }
# END_CONTRACT: test_create_new_task_unknown_engine
@pytest.mark.asyncio
async def test_create_new_task_unknown_engine(
    test_config, mock_db, mock_clouds
) -> None:
    """create_new_task raises RuntimeError for unknown engine (via patched submit_task)"""
    scheduler = make_scheduler(db=mock_db, config=test_config, clouds=mock_clouds)
    mock_submit = AsyncMock(side_effect=RuntimeError("not supported: nonexistent"))
    with (
        patch("yascheduler.scheduler.make_cli_deps", new=MagicMock()),
        patch("yascheduler.scheduler.submit_task", new=mock_submit),
    ):
        with pytest.raises(RuntimeError, match="nonexistent"):
            await scheduler.create_new_task(
                label="test",
                metadata={"input.txt": "/tmp/input.txt"},
                engine_name="nonexistent",
            )


# START_CONTRACT: test_create_new_task_missing_input_file
#   PURPOSE: Verify RuntimeError propagates when required input file is missing
#   INPUTS: { test_config, mock_db, mock_clouds - pytest fixtures }
#   OUTPUTS: { None - test assertions via pytest.raises }
# END_CONTRACT: test_create_new_task_missing_input_file
@pytest.mark.asyncio
async def test_create_new_task_missing_input_file(
    test_config, mock_db, mock_clouds
) -> None:
    """create_new_task raises RuntimeError when input file is missing"""
    scheduler = make_scheduler(db=mock_db, config=test_config, clouds=mock_clouds)
    mock_submit = AsyncMock(side_effect=RuntimeError("missing input file 'input.txt'"))
    with (
        patch("yascheduler.scheduler.make_cli_deps", new=MagicMock()),
        patch("yascheduler.scheduler.submit_task", new=mock_submit),
    ):
        with pytest.raises(RuntimeError, match="input.txt"):
            await scheduler.create_new_task(
                label="test",
                metadata={},
                engine_name="test_engine",
            )


# START_CONTRACT: test_create_new_task_success
#   PURPOSE: Verify Scheduler.create_new_task delegates to submit_task and returns TaskModel from db.get_task
#   INPUTS: { test_config, mock_db, mock_clouds - pytest fixtures }
#   OUTPUTS: { None - test assertions on returned TaskModel }
# END_CONTRACT: test_create_new_task_success
@pytest.mark.asyncio
async def test_create_new_task_success(test_config, mock_db, mock_clouds) -> None:
    """create_new_task calls submit_task, fetches result via db.get_task, returns TaskModel"""
    expected_task = TaskModel(
        task_id=1, label="test", ip="", status=TaskStatus.TO_DO, metadata={}
    )
    mock_db.get_task = AsyncMock(return_value=expected_task)
    scheduler = make_scheduler(db=mock_db, config=test_config, clouds=mock_clouds)
    with (
        patch("yascheduler.scheduler.make_cli_deps", new=MagicMock()),
        patch("yascheduler.scheduler.submit_task", new=AsyncMock(return_value=1)),
    ):
        result = await scheduler.create_new_task(
            label="test",
            metadata={"input.txt": "/tmp/input.txt"},
            engine_name="test_engine",
        )
    assert result == expected_task


class TestWebhookPayload:
    """Tests for WebhookPayload dataclass"""

    # START_CONTRACT: test_construction
    #   PURPOSE: Verify WebhookPayload construction with explicit custom_params
    #   INPUTS: { None }
    #   OUTPUTS: { None - assertions on task_id, status, custom_params fields }
    # END_CONTRACT: test_construction

    def test_construction(self) -> None:
        payload = WebhookPayload(task_id=1, status=0, custom_params={"k": "v"})
        assert payload.task_id == 1
        assert payload.status == 0
        assert payload.custom_params == {"k": "v"}

    # START_CONTRACT: test_default_custom_params
    #   PURPOSE: Verify WebhookPayload default custom_params is empty dict when not provided
    #   INPUTS: { None }
    #   OUTPUTS: { None - assertion on default custom_params value }
    # END_CONTRACT: test_default_custom_params

    def test_default_custom_params(self) -> None:
        payload = WebhookPayload(task_id=42, status=1)
        assert payload.custom_params == {}
