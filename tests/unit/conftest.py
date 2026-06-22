# FILE: tests/unit/conftest.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Auto-mark all collected tests in this directory as "unit".
#   SCOPE: pytest_collection_modifyitems hook
#   DEPENDS: none
#   LINKS: none
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   pytest_collection_modifyitems - auto-mark tests as "unit"
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Auto-mark unit tests via directory-level conftest hook.
# END_CHANGE_SUMMARY

from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.config import Engine, EngineRepository
from yascheduler.domain.model import Task, TaskContext, TaskStatus


@pytest.fixture
def engine() -> Engine:
    """A valid engine with one input file, one output file, linux platform."""
    return Engine(
        name="test_engine",
        spawn="echo {task_path}",
        check_cmd="echo ok",
        check_pname=None,
        input_files=("inp",),
        output_files=("OUTPUT",),
        platforms=("linux",),
    )


@pytest.fixture
def mock_engine_repo(engine: Engine) -> MagicMock:
    """EngineRepository that contains ``test_engine``."""
    repo = MagicMock(spec=EngineRepository)
    repo.__contains__.return_value = True
    repo.__getitem__.return_value = engine
    repo.get.return_value = engine
    return repo


@pytest.fixture
def mock_uow_factory() -> MagicMock:
    """Factory that returns a fully-mocked UnitOfWork with async methods."""
    uow = AsyncMock()
    uow.tasks = AsyncMock()
    uow.tasks.insert = AsyncMock()
    uow.tasks.save = AsyncMock()
    uow.tasks.get = AsyncMock()
    uow.commit = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=uow)


@pytest.fixture
def running_task() -> Task:
    """A RUNNING domain Task for use with consume_task."""
    return Task(
        task_id=1,
        label="test",
        context=TaskContext(
            engine="test_engine",
            remote_folder="/remote/tasks/20250101_120000_42",
        ),
        status=TaskStatus.RUNNING,
        allocated_ip="10.0.0.1",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/tests/unit/" in str(item.path):
            item.add_marker("unit")
