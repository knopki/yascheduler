"""Integration tests for TaskRowNotFoundError on 0-row UPDATE outcomes."""
# region MODULE_CONTRACT
# PURPOSE: Integration tests for TaskRowNotFoundError raised by PostgresTaskRepository.save/update_status on 0-row UPDATE.
# SCOPE: save() with non-existent task_id raises and does not append to _saved_tasks; update_status() with non-existent task_id raises.
# KEYWORDS: TaskRowNotFoundError, PostgresTaskRepository, 0-row UPDATE
# endregion MODULE_CONTRACT

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pg8000.native
import pytest

from yascheduler.domain.model import Task, TaskId
from yascheduler.domain.model import TaskStatus as DomainTaskStatus
from yascheduler.infra.persistence import TaskRowNotFoundError
from yascheduler.infra.persistence.postgres import PostgresTaskRepository
from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork


async def test_save_nonexistent_task_raises(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """save() on a non-existent task_id raises TaskRowNotFoundError and skips _saved_tasks.append."""
    nonexistent_id = TaskId(999_999)

    async with uow_factory() as uow:
        # The UoW wires its _saved_tasks list into the repository so that
        # publish_events can collect events from saved aggregates on commit.
        # A 0-row save MUST NOT append to that list (orphan-event prevention).
        saved_before = list(uow._saved_tasks)  # type: ignore[attr-defined]
        ghost = Task(
            task_id=nonexistent_id,
            label="ghost",
            engine="test_shell",
            status=DomainTaskStatus.RUNNING,
        )
        with pytest.raises(TaskRowNotFoundError) as excinfo:
            await uow.tasks.save(ghost)
        assert excinfo.value.task_id == nonexistent_id
        assert uow._saved_tasks == saved_before, (  # type: ignore[attr-defined]
            "save() must NOT append to _saved_tasks when the row is missing"
        )


async def test_update_status_nonexistent_task_raises(
    pg_conn: pg8000.native.Connection,
    pg_executor: ThreadPoolExecutor,
) -> None:
    """update_status() on a non-existent task_id raises TaskRowNotFoundError."""
    repo = PostgresTaskRepository(pg_conn, pg_executor)
    nonexistent_id = TaskId(999_998)
    with pytest.raises(TaskRowNotFoundError) as excinfo:
        await repo.update_status(nonexistent_id, DomainTaskStatus.RUNNING)
    assert excinfo.value.task_id == nonexistent_id
