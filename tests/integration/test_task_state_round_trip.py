"""Integration tests for Task state-payload persistence round-trip."""
# region MODULE_CONTRACT
# PURPOSE: Verify the row↔Task hydration round-trips each state value object against real PostgreSQL via testcontainers.
# SCOPE: Insert a task, drive it TO_DO→RUNNING→DONE, save and reload at each state, assert the reloaded task.state matches.
# KEYWORDS: hydration, round-trip, state-payload, Todo, Running, Done
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from yascheduler.domain.model import (
    Done,
    NewNode,
    NewTask,
    Running,
    TaskId,
    TaskStatus,
    Todo,
    allocated_node_id_of,
    error_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

pytestmark = pytest.mark.integration


async def test_state_round_trip_through_all_lifecycle_states(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """A task saved at each lifecycle state reloads with the matching state object."""
    async with uow_factory() as uow:
        node = await uow.nodes.insert(
            NewNode(hostname="10.0.0.1", ncpus=2, enabled=True),
        )
        task = await uow.tasks.insert(NewTask(label="job", engine="fleur"))
        await uow.commit()
        task_id = task.task_id
        node_id = node.node_id

    # TO_DO: default state after insert.
    async with uow_factory() as uow:
        reloaded = await uow.tasks.get(task_id)
        await uow.commit()
    assert reloaded is not None
    assert isinstance(reloaded.state, Todo)
    assert reloaded.status is TaskStatus.TO_DO
    assert reloaded.state.remote_folder is None
    assert allocated_node_id_of(reloaded) is None
    assert error_of(reloaded) is None

    # RUNNING: bind the node.
    async with uow_factory() as uow:
        task = await uow.tasks.get_todo(task_id)
        assert task is not None
        running = task.run(node_id, "/remote/job")
        await uow.tasks.save(running, expected_status=TaskStatus.TO_DO)
        await uow.commit()

    async with uow_factory() as uow:
        reloaded = await uow.tasks.get(task_id)
        await uow.commit()
    assert reloaded is not None
    assert isinstance(reloaded.state, Running)
    assert reloaded.status is TaskStatus.RUNNING
    assert reloaded.state.allocated_node_id == node_id
    assert reloaded.state.remote_folder == "/remote/job"
    assert error_of(reloaded) is None

    # DONE: complete successfully, carrying the allocation into Done.
    async with uow_factory() as uow:
        task = await uow.tasks.get_running(task_id)
        assert task is not None
        done = task.complete(local_folder="/local/out", remote_folder="/remote/job")
        await uow.tasks.save(done, expected_status=TaskStatus.RUNNING)
        await uow.commit()

    async with uow_factory() as uow:
        reloaded = await uow.tasks.get(task_id)
        await uow.commit()
    assert reloaded is not None
    assert isinstance(reloaded.state, Done)
    assert reloaded.status is TaskStatus.DONE
    assert reloaded.state.error is None
    assert reloaded.state.allocated_node_id == node_id
    assert reloaded.state.remote_folder == "/remote/job"
    assert reloaded.local_folder == "/local/out"


async def test_done_state_preserves_independent_optional_fields(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Done state hydrates the legal (allocated_node_id NULL, remote_folder NOT NULL) pair."""
    async with uow_factory() as uow:
        task = await uow.tasks.insert(NewTask(label="rejected", engine="fleur"))
        # Reject from TO_DO with a pre-filled folder: Done carries remote_folder,
        # allocated_node_id NULL, error set — the independent-Optional case the
        # Allocation VO could not represent.
        rejected = task.reject("unsupported engine")
        await uow.tasks.save(rejected, expected_status=TaskStatus.TO_DO)
        await uow.commit()
        task_id = task.task_id

    async with uow_factory() as uow:
        reloaded = await uow.tasks.get(task_id)
        await uow.commit()
    assert reloaded is not None
    assert isinstance(reloaded.state, Done)
    assert reloaded.state.error == "unsupported engine"
    assert reloaded.state.allocated_node_id is None
    assert reloaded.state.remote_folder is None


async def test_get_running_returns_none_for_wrong_status_or_missing_row(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """get_running returns None when the row is absent OR in a different status."""
    async with uow_factory() as uow:
        task = await uow.tasks.insert(NewTask(label="job", engine="fleur"))
        await uow.commit()
        task_id = task.task_id
        node = await uow.nodes.insert(
            NewNode(hostname="10.0.0.2", ncpus=2, enabled=True),
        )
        node_id = node.node_id

    # TO_DO row: get_running is None, get_todo returns the task.
    async with uow_factory() as uow:
        running_none = await uow.tasks.get_running(task_id)
        todo = await uow.tasks.get_todo(task_id)
        await uow.commit()
    assert running_none is None
    assert todo is not None
    assert isinstance(todo.state, Todo)

    # Transition to RUNNING: get_todo now None, get_running returns the task.
    async with uow_factory() as uow:
        task = await uow.tasks.get_todo(task_id)
        assert task is not None
        running = task.run(node_id, "/remote/job")
        await uow.tasks.save(running, expected_status=TaskStatus.TO_DO)
        await uow.commit()

    async with uow_factory() as uow:
        todo_none = await uow.tasks.get_todo(task_id)
        running_task = await uow.tasks.get_running(task_id)
        await uow.commit()
    assert todo_none is None
    assert running_task is not None
    assert isinstance(running_task.state, Running)

    # Missing row entirely: both return None.
    async with uow_factory() as uow:
        missing_id = TaskId(999_999)
        assert await uow.tasks.get_running(missing_id) is None
        assert await uow.tasks.get_todo(missing_id) is None
        await uow.commit()
