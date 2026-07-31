"""Integration tests for TaskRowNotFoundError on 0-row UPDATE outcomes."""
# region MODULE_CONTRACT
# PURPOSE: Integration tests for TaskRowNotFoundError raised by PostgresTaskRepository.save/update_status on 0-row UPDATE.
# SCOPE: save() with non-existent task_id raises and does not append to _saved_tasks; update_status() with non-existent task_id raises; save(expected_status=...) raises when the DB status differs from the guard (double-allocation / lost-update).
# KEYWORDS: TaskRowNotFoundError, PostgresTaskRepository, 0-row UPDATE, status guard, double-allocation
# endregion MODULE_CONTRACT

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pg8000.native
import pytest

from yascheduler.domain.model import NewNode, NewTask, Task, TaskId
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


async def test_save_expected_status_rejects_double_allocation(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """save(expected_status=TO_DO) raises when the row was already claimed (RUNNING).

    Reproduces the cross-host double-allocation race: the row exists but its
    status no longer matches the guard, so the UPDATE matches zero rows and the
    data-corrupting overwrite is refused.
    """
    # Insert two nodes so the FK on allocated_node_id is satisfied.
    async with uow_factory() as uow:
        inserted = await uow.tasks.insert(NewTask(label="race", engine="test_shell"))
        node_a = await uow.nodes.insert(
            NewNode(hostname="10.0.0.1", ncpus=1, enabled=True)
        )
        node_b = await uow.nodes.insert(
            NewNode(hostname="10.0.0.2", ncpus=1, enabled=True)
        )
        await uow.commit()

    # First daemon claims the task: TO_DO → RUNNING.
    async with uow_factory() as uow:
        claimed = inserted.run(node_a.node_id, "/remote/race")
        await uow.tasks.save(claimed, expected_status=DomainTaskStatus.TO_DO)
        await uow.commit()

    # Second daemon attempts the same claim with a stale TO_DO view — rejected.
    async with uow_factory() as uow:
        stale_claim = inserted.run(node_b.node_id, "/remote/other")
        with pytest.raises(TaskRowNotFoundError) as excinfo:
            await uow.tasks.save(stale_claim, expected_status=DomainTaskStatus.TO_DO)
        assert excinfo.value.task_id == inserted.task_id

    # The first daemon's claim is untouched (no silent overwrite).
    async with uow_factory() as uow:
        survivor = await uow.tasks.get(inserted.task_id)
        assert survivor is not None
        assert survivor.status is DomainTaskStatus.RUNNING
        assert survivor.allocated_node_id == node_a.node_id
        assert survivor.remote_folder == "/remote/race"
