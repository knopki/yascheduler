# FILE: tests/unit/test_query_tasks.py
# VERSION: 1.0.1
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for the query_tasks use case (5 QueryTasks scenarios).
#   SCOPE: status dispatch, jobs dispatch, both-supplied ValueError, neither empty, read-only no commit.
#   DEPENDS: M-APPLICATION-QUERY-TASKS
#   LINKS: M-APPLICATION-QUERY-TASKS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   FakeTaskRepository - In-memory task repo capturing list_by_status/list_by_jobs calls
#   FakeUnitOfWork - In-memory UoW exposing FakeTaskRepository, tracking commit calls
#   TestQueryTasks - 5 QueryTasks spec scenarios against fakes
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: [v1.0.1 - Add `from __future__ import annotations` to restore Python 3.9 compatibility (PEP 604 `X | None` in FakeTaskRepository signatures).]
#   PREVIOUS_CHANGE: [v1.0.0 - Initial QueryTasks use case unit tests (client-query-uow).]
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from yascheduler.application.query_tasks import query_tasks
from yascheduler.domain.model import Task, TaskContext, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.application.uow import AbstractUnitOfWork


class FakeTaskRepository:
    """In-memory task repository capturing dispatched query calls."""

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._tasks = tasks or []
        self.list_by_status_calls: list[set[TaskStatus]] = []
        self.list_by_jobs_calls: list[list[int]] = []

    async def list_by_status(
        self, statuses: set[TaskStatus], *, limit: int | None = None
    ) -> list[Task]:
        self.list_by_status_calls.append(statuses)
        return self._tasks

    async def list_by_jobs(self, job_ids: list[int]) -> list[Task]:
        self.list_by_jobs_calls.append(job_ids)
        return self._tasks


class FakeUnitOfWork:
    """In-memory UoW exposing a FakeTaskRepository and tracking commit calls."""

    def __init__(self, repo: FakeTaskRepository) -> None:
        self.tasks = repo
        self.commit_calls = 0

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:  # noqa: ANN001
        return False

    async def commit(self) -> None:
        self.commit_calls += 1


def _make_task(task_id: int = 1, status: TaskStatus = TaskStatus.TO_DO) -> Task:
    return Task(
        task_id=task_id,
        label=f"task-{task_id}",
        context=TaskContext(engine="test_engine"),
        status=status,
    )


def _factory(
    uow: FakeUnitOfWork,
) -> Callable[[], AbstractUnitOfWork]:
    def factory() -> AbstractUnitOfWork:
        return uow  # type: ignore[return-value]

    return factory


class TestQueryTasks:
    """5 QueryTasks spec scenarios against FakeUnitOfWork + FakeTaskRepository."""

    async def test_query_by_statuses_dispatches_list_by_status(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task(status=TaskStatus.TO_DO)])
        uow = FakeUnitOfWork(repo)

        result = await query_tasks(
            jobs=None, statuses=[TaskStatus.TO_DO], uow_factory=_factory(uow)
        )

        assert len(result) == 1
        assert result[0].task_id == 1
        assert repo.list_by_status_calls == [{TaskStatus.TO_DO}]
        assert repo.list_by_jobs_calls == []

    async def test_query_by_jobs_dispatches_list_by_jobs(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)

        result = await query_tasks(
            jobs=[1, 2, 3], statuses=None, uow_factory=_factory(uow)
        )

        assert len(result) == 1
        assert repo.list_by_jobs_calls == [[1, 2, 3]]
        assert repo.list_by_status_calls == []

    async def test_both_jobs_and_statuses_raises_value_error(self) -> None:
        factory = MagicMock(side_effect=AssertionError("UoW should not be opened"))

        with pytest.raises(ValueError, match="mutually exclusive"):
            await query_tasks(
                jobs=[1], statuses=[TaskStatus.TO_DO], uow_factory=factory
            )

        factory.assert_not_called()

    async def test_neither_jobs_nor_statuses_returns_empty(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        factory = MagicMock(side_effect=AssertionError("UoW should not be opened"))

        result = await query_tasks(jobs=None, statuses=None, uow_factory=factory)

        assert result == []
        factory.assert_not_called()
        assert repo.list_by_status_calls == []
        assert repo.list_by_jobs_calls == []

    async def test_use_case_is_read_only_no_commit(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)

        await query_tasks(jobs=[1], statuses=None, uow_factory=_factory(uow))

        assert uow.commit_calls == 0
