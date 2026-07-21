# region MODULE_CONTRACT
# PURPOSE: Unit tests for the query_tasks use case (7 QueryTasks scenarios + node batch-load).
# SCOPE: status dispatch, jobs dispatch, both-supplied ValueError, neither empty, read-only no commit, all-unallocated nodes empty, distinct node ids batch-loaded once, status with node loading.
# KEYWORDS: query_tasks, status dispatch, jobs dispatch, node batch-load
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from yascheduler.application.query_tasks import query_tasks
from yascheduler.domain.model import Node, NodeId, Task, TaskId, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.application.uow import AbstractUnitOfWork


class FakeTaskRepository:
    """In-memory task repository capturing dispatched query calls."""

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._tasks = tasks or []
        self.list_by_status_calls: list[set[TaskStatus]] = []
        self.list_by_jobs_calls: list[list[TaskId]] = []

    async def list_by_status(
        self,
        statuses: set[TaskStatus],
        *,
        limit: int | None = None,
    ) -> list[Task]:
        self.list_by_status_calls.append(statuses)
        return self._tasks

    async def list_by_jobs(self, job_ids: list[TaskId]) -> list[Task]:
        self.list_by_jobs_calls.append(job_ids)
        return self._tasks


class FakeNodeRepository:
    """In-memory node repository storing nodes and capturing get_by_ids calls."""

    def __init__(self, nodes: list[Node] | None = None) -> None:
        self._nodes = {n.node_id: n for n in (nodes or [])}
        self.get_by_ids_calls: list[list[NodeId]] = []

    async def get_by_ids(self, node_ids: list[NodeId]) -> dict[NodeId, Node]:
        self.get_by_ids_calls.append(node_ids)
        return {nid: self._nodes[nid] for nid in node_ids if nid in self._nodes}


class FakeUnitOfWork:
    """In-memory UoW exposing FakeTaskRepository + FakeNodeRepository and tracking commit calls."""

    def __init__(
        self,
        repo: FakeTaskRepository,
        nodes: FakeNodeRepository | None = None,
    ) -> None:
        self.tasks = repo
        self.nodes = nodes or FakeNodeRepository()
        self.commit_calls = 0

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False

    async def commit(self) -> None:
        self.commit_calls += 1


def _make_task(
    task_id: int = 1,
    status: TaskStatus = TaskStatus.TO_DO,
    allocated_node_id: NodeId | None = None,
) -> Task:
    from datetime import datetime

    return Task(
        task_id=TaskId(task_id),
        label=f"task-{task_id}",
        engine="test_engine",
        remote_folder=None,
        local_folder=None,
        webhook_url=None,
        webhook_custom_params={},
        error=None,
        extra={},
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
        status=status,
        allocated_node_id=allocated_node_id,
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

        tasks, nodes_by_id = await query_tasks(
            jobs=None,
            statuses=[TaskStatus.TO_DO],
            uow_factory=_factory(uow),
        )

        assert len(tasks) == 1
        assert tasks[0].task_id == TaskId(1)
        assert nodes_by_id == {}
        assert repo.list_by_status_calls == [{TaskStatus.TO_DO}]
        assert repo.list_by_jobs_calls == []

    async def test_query_by_jobs_dispatches_list_by_jobs(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)

        tasks, nodes_by_id = await query_tasks(
            jobs=[TaskId(1), TaskId(2), TaskId(3)],
            statuses=None,
            uow_factory=_factory(uow),
        )

        assert len(tasks) == 1
        assert tasks[0].task_id == TaskId(1)
        assert nodes_by_id == {}
        assert repo.list_by_jobs_calls == [[TaskId(1), TaskId(2), TaskId(3)]]
        assert repo.list_by_status_calls == []

    async def test_both_jobs_and_statuses_raises_value_error(self) -> None:
        factory = MagicMock(side_effect=AssertionError("UoW should not be opened"))

        with pytest.raises(ValueError, match="mutually exclusive"):
            await query_tasks(
                jobs=[TaskId(1)],
                statuses=[TaskStatus.TO_DO],
                uow_factory=factory,
            )

        factory.assert_not_called()

    async def test_neither_jobs_nor_statuses_returns_empty(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        factory = MagicMock(side_effect=AssertionError("UoW should not be opened"))

        result = await query_tasks(jobs=None, statuses=None, uow_factory=factory)

        assert result == ([], {})
        factory.assert_not_called()
        assert repo.list_by_status_calls == []
        assert repo.list_by_jobs_calls == []

    async def test_use_case_is_read_only_no_commit(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)

        await query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=_factory(uow))

        assert uow.commit_calls == 0

    async def test_all_unallocated_returns_empty_nodes(self) -> None:
        """All tasks unallocated returns empty nodes dict — get_by_ids NOT called."""
        task = _make_task(status=TaskStatus.TO_DO)  # allocated_node_id=None by default
        repo = FakeTaskRepository(tasks=[task])
        nodes_repo = FakeNodeRepository()
        uow = FakeUnitOfWork(repo, nodes=nodes_repo)

        tasks, nodes_by_id = await query_tasks(
            jobs=None,
            statuses=[TaskStatus.TO_DO],
            uow_factory=_factory(uow),
        )

        assert len(tasks) == 1
        assert nodes_by_id == {}
        assert nodes_repo.get_by_ids_calls == []

    async def test_distinct_allocated_node_ids_batch_loaded_once(self) -> None:
        """Distinct allocated_node_ids are batch-loaded once (deduplicated, no None)."""
        tasks_list = [
            _make_task(task_id=1, allocated_node_id=NodeId(7)),
            _make_task(task_id=2, allocated_node_id=NodeId(7)),
            _make_task(task_id=3, allocated_node_id=NodeId(8)),
            _make_task(task_id=4, allocated_node_id=None),
        ]
        nodes_list = [
            Node(node_id=NodeId(7), hostname="10.0.0.7", ncpus=2),
            Node(node_id=NodeId(8), hostname="10.0.0.8", ncpus=4),
        ]
        repo = FakeTaskRepository(tasks=tasks_list)
        nodes_repo = FakeNodeRepository(nodes=nodes_list)
        uow = FakeUnitOfWork(repo, nodes=nodes_repo)

        tasks, nodes_by_id = await query_tasks(
            jobs=[TaskId(1), TaskId(2), TaskId(3), TaskId(4)],
            statuses=None,
            uow_factory=_factory(uow),
        )

        assert len(tasks) == 4
        assert nodes_by_id == {NodeId(7): nodes_list[0], NodeId(8): nodes_list[1]}
        assert nodes_repo.get_by_ids_calls == [[NodeId(7), NodeId(8)]]

    async def test_query_by_statuses_loads_nodes(self) -> None:
        """Query by statuses dispatches to list_by_status and loads nodes."""
        task = _make_task(
            task_id=1,
            status=TaskStatus.TO_DO,
            allocated_node_id=NodeId(7),
        )
        node = Node(node_id=NodeId(7), hostname="10.0.0.1", ncpus=2)
        repo = FakeTaskRepository(tasks=[task])
        nodes_repo = FakeNodeRepository(nodes=[node])
        uow = FakeUnitOfWork(repo, nodes=nodes_repo)

        tasks, nodes_by_id = await query_tasks(
            jobs=None,
            statuses=[TaskStatus.TO_DO],
            uow_factory=_factory(uow),
        )

        assert len(tasks) == 1
        assert nodes_by_id == {NodeId(7): node}
