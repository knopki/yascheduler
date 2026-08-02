# region MODULE_CONTRACT
# PURPOSE: Auto-mark all collected tests in this directory as "unit"; isolate global SQL query cache.
# SCOPE: pytest_collection_modifyitems hook, autouse cache-isolation fixture.
# KEYWORDS: pytest auto-mark, unit tests, cache isolation
# endregion MODULE_CONTRACT

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.domain import Engine, EngineRepository
from yascheduler.domain.model import NodeId, Running, Task, TaskId
from yascheduler.infra.persistence.sql_loader import load_query


@pytest.fixture(autouse=True)
def _isolate_sql_query_cache() -> Generator[None, None, None]:
    """Clear load_query cache around each test to stop cross-suite cache pollution."""
    load_query.cache_clear()
    yield
    load_query.cache_clear()


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
        task_id=TaskId(1),
        label="test",
        engine="test_engine",
        state=Running(
            allocated_node_id=NodeId(1),
            remote_folder="/remote/tasks/20250101_120000_42",
        ),
        webhook_url=None,
        webhook_custom_params={},
        extra={},
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/tests/unit/" in str(item.path):
            item.add_marker("unit")
