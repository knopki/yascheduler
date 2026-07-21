"""Unit tests for Yascheduler queue-query methods.

Exercises the post-swap implementation via the `deps_factory` constructor
seam: a `FakeCLIDeps`-returning factory whose `uow_factory()` returns a
`FakeUnitOfWork` carrying a `FakeTaskRepository`. The seam keeps these
tests stable across future refactors of the query body.
"""
# region MODULE_CONTRACT
# PURPOSE: Unit tests for Yascheduler queue-query methods via the deps_factory constructor seam.
# SCOPE: status/jobs dispatch, mutual-exclusivity ValueError, empty-in empty-out, 5-key dict shape with nested node, node object for allocated/unallocated, factory-per-call.
# KEYWORDS: Yascheduler queue query, status/jobs dispatch, dict shape
# endregion MODULE_CONTRACT

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from yascheduler.domain.model import Node, NodeId, Task, TaskId, TaskStatus
from yascheduler.entrypoints.client import Yascheduler

EXPECTED_KEYS = {"task_id", "label", "status", "metadata", "node"}


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
    """In-memory node repository returning stored nodes for get_by_ids queries."""

    def __init__(self, nodes: list[Node] | None = None) -> None:
        self._nodes = {n.node_id: n for n in (nodes or [])}

    async def get_by_ids(self, node_ids: list[NodeId]) -> dict[NodeId, Node]:
        return {nid: self._nodes[nid] for nid in node_ids if nid in self._nodes}


class FakeUnitOfWork:
    """In-memory UoW exposing FakeTaskRepository + FakeNodeRepository."""

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


class FakeCLIDeps:
    """Lightweight CLIDeps stub — only `uow_factory` is exercised by the query path."""

    def __init__(self, uow: FakeUnitOfWork) -> None:
        self.uow_factory = lambda: uow
        # Unused by query path; present to mirror CLIDeps shape.
        self.engines = SimpleNamespace()


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


def _build_client(uow: FakeUnitOfWork) -> Yascheduler:
    """Construct a Yascheduler with Config.from_config_parser patched out and deps_factory wired."""
    fake_deps = FakeCLIDeps(uow)
    with patch("yascheduler.entrypoints.client.parse_config") as mock_cfg:
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
        assert repo.list_by_jobs_calls == [[TaskId(7)]]
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

    async def test_node_object_for_allocated_task(self) -> None:
        """Task with allocated_node_id returns nested node object with hostname, port, username, cloud, and new fields."""
        node = Node(
            node_id=NodeId(7),
            hostname="10.0.0.1",
            ncpus=2,
            port=22,
            username="root",
            cloud="hetzner",
        )
        repo = FakeTaskRepository(
            tasks=[_make_task(task_id=1, allocated_node_id=NodeId(7))],
        )
        nodes_repo = FakeNodeRepository(nodes=[node])
        uow = FakeUnitOfWork(repo, nodes=nodes_repo)
        client = _build_client(uow)

        result = await client.queue_get_tasks_async(jobs=[1])

        assert len(result) == 1
        mapping = result[0]
        node_dict = mapping["node"]
        assert node_dict["hostname"] == "10.0.0.1"
        assert node_dict["port"] == 22
        assert node_dict["username"] == "root"
        assert node_dict["cloud"] == "hetzner"
        assert node_dict["jump_host"] is None
        assert node_dict["jump_port"] == 22
        assert node_dict["jump_username"] == "root"
        assert node_dict["external_id"] is None
        assert node_dict["status"] == "OTHER"
        assert "created_at" in node_dict
        assert "updated_at" in node_dict

    async def test_node_is_null_for_unallocated_task(self) -> None:
        """Task with allocated_node_id=None has node is None."""
        repo = FakeTaskRepository(tasks=[_make_task(allocated_node_id=None)])
        uow = FakeUnitOfWork(repo)
        client = _build_client(uow)

        result = await client.queue_get_tasks_async(jobs=[1])

        assert len(result) == 1
        mapping = result[0]
        assert mapping["node"] is None

    async def test_flat_ip_and_cloud_keys_absent(self) -> None:
        """Flat ip and cloud keys are absent from the returned mapping."""
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)
        client = _build_client(uow)

        result = await client.queue_get_tasks_async(jobs=[1])

        assert len(result) == 1
        mapping = result[0]
        assert "ip" not in mapping
        assert "cloud" not in mapping

    async def test_returned_dict_shape_and_types(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task(allocated_node_id=None)])
        uow = FakeUnitOfWork(repo)
        client = _build_client(uow)

        result = await client.queue_get_tasks_async(jobs=[1])

        assert len(result) == 1
        mapping = result[0]
        assert set(mapping.keys()) == EXPECTED_KEYS
        assert isinstance(mapping["status"], TaskStatus)
        assert mapping["status"] is TaskStatus.TO_DO
        assert mapping["node"] is None
        assert isinstance(mapping["metadata"], dict)


class TestDepsFactoryInvocation:
    """dependency-injection spec: factory invoked once per query call (no caching)."""

    async def test_factory_invoked_once_per_call(self) -> None:
        repo = FakeTaskRepository(tasks=[_make_task()])
        uow = FakeUnitOfWork(repo)
        fake_deps = FakeCLIDeps(uow)

        invocation_count = 0

        def counting_factory(cfg) -> FakeCLIDeps:
            nonlocal invocation_count
            invocation_count += 1
            return fake_deps

        with patch("yascheduler.entrypoints.client.parse_config") as mock_cfg:
            mock_cfg.return_value = SimpleNamespace()
            # FakeCLIDeps is a structural stand-in for CLIDeps; the seam is test-only.
            client = Yascheduler(deps_factory=counting_factory)  # type: ignore[arg-type]

            await client.queue_get_tasks_async(jobs=[1])
            await client.queue_get_tasks_async(jobs=[1])

        assert invocation_count == 2
