# FILE: tests/unit/test_client_query.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for Yascheduler queue-query methods via the deps_factory constructor seam.
#   SCOPE: status/jobs dispatch, mutual-exclusivity ValueError, empty-in empty-out, 6-key shape, factory-per-call.
#   DEPENDS: M-CLIENT, M-APPLICATION-QUERY-TASKS, M-DOMAIN-MODEL
#   LINKS: M-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   FakeTaskRepository - In-memory task repo capturing list_by_status/list_by_jobs calls
#   FakeUnitOfWork - In-memory UoW exposing FakeTaskRepository
#   FakeCLIDeps - Lightweight CLIDeps stub exposing uow_factory only
#   TestClientQueryDispatch - 5 testing-unit scenarios via deps_factory
#   TestDepsFactoryInvocation - Factory invoked once per queue_get_tasks_async call (no caching)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial unit tests for client query path post-swap (client-query-uow).
# END_CHANGE_SUMMARY

"""Unit tests for Yascheduler queue-query methods.

Exercises the post-swap implementation via the `deps_factory` constructor
seam: a `FakeCLIDeps`-returning factory whose `uow_factory()` returns a
`FakeUnitOfWork` carrying a `FakeTaskRepository`. The seam keeps these
tests stable across future refactors of the query body.
"""

from pathlib import PurePath
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from yascheduler.client import Yascheduler
from yascheduler.domain.model import Task, TaskContext, TaskStatus

EXPECTED_KEYS = {"task_id", "label", "ip", "status", "metadata", "cloud"}


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
    """In-memory UoW exposing a FakeTaskRepository as `tasks`."""

    def __init__(self, repo: FakeTaskRepository) -> None:
        self.tasks = repo
        self.commit_calls = 0

    async def __aenter__(self) -> "FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:  # noqa: ANN001
        return False

    async def commit(self) -> None:
        self.commit_calls += 1


class FakeCLIDeps:
    """Lightweight CLIDeps stub — only `uow_factory` is exercised by the query path."""

    def __init__(self, uow: FakeUnitOfWork) -> None:
        self.uow_factory = lambda: uow
        # Unused by query path; present to mirror CLIDeps shape.
        self.engines = SimpleNamespace()
        self.remote_tasks_dir = PurePath("/tmp/tasks")


def _make_task(
    task_id: int = 1,
    status: TaskStatus = TaskStatus.TO_DO,
    allocated_ip: str | None = None,
) -> Task:
    return Task(
        task_id=task_id,
        label=f"task-{task_id}",
        context=TaskContext(engine="test_engine"),
        status=status,
        allocated_ip=allocated_ip,
    )


def _build_client(uow: FakeUnitOfWork) -> Yascheduler:
    """Construct a Yascheduler with Config.from_config_parser patched out and deps_factory wired."""
    fake_deps = FakeCLIDeps(uow)
    with patch("yascheduler.client.Config.from_config_parser") as mock_cfg:
        mock_cfg.return_value = SimpleNamespace()
        # FakeCLIDeps is a structural stand-in for CLIDeps; the seam is test-only.
        return Yascheduler(deps_factory=lambda cfg: fake_deps)  # type: ignore[arg-type]


class TestClientQueryDispatch:
    """5 testing-unit spec scenarios for Yascheduler.queue_get_tasks_async."""

    async def test_status_filter_dispatches_list_by_status(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task(status=TaskStatus.TO_DO)])
        uow = FakeUnitOfWork(repo)
        client = _build_client(uow)

        result = await client.queue_get_tasks_async(status=[0])

        assert len(result) == 1
        assert repo.list_by_status_calls == [{TaskStatus.TO_DO}]
        assert repo.list_by_jobs_calls == []

    async def test_jobs_filter_dispatches_list_by_jobs(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task(task_id=7)])
        uow = FakeUnitOfWork(repo)
        client = _build_client(uow)

        result = await client.queue_get_tasks_async(jobs=[7])

        assert len(result) == 1
        assert repo.list_by_jobs_calls == [[7]]
        assert repo.list_by_status_calls == []

    async def test_both_filters_raises_value_error(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)
        client = _build_client(uow)

        with pytest.raises(ValueError, match="mutually exclusive"):
            await client.queue_get_tasks_async(jobs=[1], status=[0])

    async def test_neither_filter_returns_empty(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)
        client = _build_client(uow)

        result = await client.queue_get_tasks_async()

        assert result == []
        assert repo.list_by_status_calls == []
        assert repo.list_by_jobs_calls == []

    async def test_returned_dict_shape_and_types(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task(allocated_ip=None)])
        uow = FakeUnitOfWork(repo)
        client = _build_client(uow)

        result = await client.queue_get_tasks_async(jobs=[1])

        assert len(result) == 1
        mapping = result[0]
        assert set(mapping.keys()) == EXPECTED_KEYS
        assert isinstance(mapping["status"], TaskStatus)
        assert mapping["status"] is TaskStatus.TO_DO
        assert mapping["ip"] == ""
        assert mapping["cloud"] is None
        assert isinstance(mapping["metadata"], dict)


class TestDepsFactoryInvocation:
    """dependency-injection spec: factory invoked once per query call (no caching)."""

    async def test_factory_invoked_once_per_call(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)
        fake_deps = FakeCLIDeps(uow)

        invocation_count = 0

        def counting_factory(cfg) -> FakeCLIDeps:  # noqa: ANN001
            nonlocal invocation_count
            invocation_count += 1
            return fake_deps

        with patch("yascheduler.client.Config.from_config_parser") as mock_cfg:
            mock_cfg.return_value = SimpleNamespace()
            # FakeCLIDeps is a structural stand-in for CLIDeps; the seam is test-only.
            client = Yascheduler(deps_factory=counting_factory)  # type: ignore[arg-type]

            await client.queue_get_tasks_async(jobs=[1])
            await client.queue_get_tasks_async(jobs=[1])

        assert invocation_count == 2
