# FILE: tests/unit/test_persistence_allocated_node_id.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for the task-allocated-node-id persistence-layer changes: _row_to_task reads NodeId, insert/save bind :node_id, and the 5 task SQL files include allocated_node_id.
#   SCOPE: _row_to_task NodeId wrapping + NULL handling; insert/save :node_id binding (value and None); SQL-file content for the 5 task files that feed _row_to_task and the 3 status/aggregate files that do NOT.
#   DEPENDS: M-PERSISTENCE-POSTGRES, M-PERSISTENCE-SQLLOADER, M-DOMAIN-MODEL
#   LINKS: M-PERSISTENCE-POSTGRES, M-PERSISTENCE-SQLLOADER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestRowToTaskAllocatedNodeId - _row_to_task reads allocated_node_id → NodeId; NULL/missing key → None
#   TestInsertSaveBindAllocatedNodeId - insert/save bind :node_id (value or None)
#   TestTaskSqlIncludesAllocatedNodeId - 5 task SQL files include allocated_node_id; 3 status/aggregate files do NOT
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - task-allocated-node-id: extract allocated_node_id persistence tests from test_persistence_adapter.py into a focused module (the parent file exceeded the 1000-line GRACE-lite hard limit after the additions).
# END_CHANGE_SUMMARY

from pytest_mock import MockerFixture

from yascheduler.domain.model import (
    NewTask,
    NodeId,
    Task,
    TaskContext,
    TaskId,
)
from yascheduler.domain.model import (
    TaskStatus as DomainTaskStatus,
)
from yascheduler.infra.persistence.postgres import PostgresTaskRepository
from yascheduler.infra.persistence.sql_loader import load_query


def _make_repo(mocker: MockerFixture) -> PostgresTaskRepository:
    """Build a minimal PostgresTaskRepository with a mock _run."""
    repo = PostgresTaskRepository.__new__(PostgresTaskRepository)
    repo._saved_tasks = None
    mock_run = mocker.AsyncMock()
    mocker.patch.object(repo, "_run", mock_run)
    return repo


class TestRowToTaskAllocatedNodeId:
    """_row_to_task reads allocated_node_id and wraps NodeId (None when NULL/absent)."""

    async def test_reads_allocated_node_id(self, mocker: MockerFixture) -> None:
        repo = _make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 1,
                "label": "job",
                "ip": "10.0.0.1",
                "status": 1,
                "metadata": '{"engine":"fleur"}',
                "allocated_node_id": 5,
            }
        ]

        task = await repo.get(TaskId(1))

        assert task is not None
        assert task.allocated_node_id == NodeId(5)

    async def test_handles_null_allocated_node_id(self, mocker: MockerFixture) -> None:
        repo = _make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 1,
                "label": "job",
                "ip": None,
                "status": 0,
                "metadata": '{"engine":"fleur"}',
                "allocated_node_id": None,
            }
        ]

        task = await repo.get(TaskId(1))

        assert task is not None
        assert task.allocated_node_id is None

    async def test_handles_missing_allocated_node_id_key(
        self, mocker: MockerFixture
    ) -> None:
        repo = _make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 1,
                "label": "job",
                "ip": None,
                "status": 0,
                "metadata": '{"engine":"fleur"}',
                # allocated_node_id key absent
            }
        ]

        task = await repo.get(TaskId(1))

        assert task is not None
        assert task.allocated_node_id is None


class TestInsertSaveBindAllocatedNodeId:
    """insert/save bind :node_id (value when allocated_node_id set, None otherwise)."""

    async def test_insert_binds_allocated_node_id(self, mocker: MockerFixture) -> None:
        repo = _make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 99,
                "label": "job",
                "ip": None,
                "status": 0,
                "metadata": '{"engine":"fleur"}',
                "allocated_node_id": 5,
            }
        ]

        new_task = NewTask(
            label="job",
            context=TaskContext(engine="fleur"),
            status=DomainTaskStatus.TO_DO,
            allocated_node_id=NodeId(5),
        )
        result = await repo.insert(new_task)

        _, kwargs = repo._run.call_args  # type: ignore[attr-defined]
        assert kwargs["node_id"] == 5
        assert result.allocated_node_id == NodeId(5)

    async def test_insert_binds_null_allocated_node_id_by_default(
        self, mocker: MockerFixture
    ) -> None:
        repo = _make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 99,
                "label": "job",
                "ip": None,
                "status": 0,
                "metadata": '{"engine":"fleur"}',
                "allocated_node_id": None,
            }
        ]

        new_task = NewTask(
            label="job",
            context=TaskContext(engine="fleur"),
            status=DomainTaskStatus.TO_DO,
        )
        await repo.insert(new_task)

        _, kwargs = repo._run.call_args  # type: ignore[attr-defined]
        assert kwargs["node_id"] is None

    async def test_save_binds_allocated_node_id(self, mocker: MockerFixture) -> None:
        repo = _make_repo(mocker)
        task = Task(
            task_id=TaskId(7),
            label="job",
            context=TaskContext(engine="fleur"),
            status=DomainTaskStatus.RUNNING,
            allocated_ip="10.0.0.1",
            allocated_node_id=NodeId(7),
        )

        await repo.save(task)

        _, kwargs = repo._run.call_args  # type: ignore[attr-defined]
        assert kwargs["node_id"] == 7

    async def test_save_binds_null_allocated_node_id(
        self, mocker: MockerFixture
    ) -> None:
        repo = _make_repo(mocker)
        task = Task(
            task_id=TaskId(7),
            label="job",
            context=TaskContext(engine="fleur"),
            status=DomainTaskStatus.TO_DO,
        )

        await repo.save(task)

        _, kwargs = repo._run.call_args  # type: ignore[attr-defined]
        assert kwargs["node_id"] is None


class TestTaskSqlIncludesAllocatedNodeId:
    """The 5 task SQL files that feed _row_to_task include allocated_node_id; the 3 status/aggregate files do NOT."""

    def test_insert_sql_includes_allocated_node_id(self) -> None:
        sql = load_query("task/insert")
        assert "allocated_node_id" in sql
        assert ":node_id" in sql
        # RETURNING includes allocated_node_id
        assert "RETURNING" in sql
        returning = sql[sql.index("RETURNING") :]
        assert "allocated_node_id" in returning

    def test_update_by_id_sql_includes_allocated_node_id(self) -> None:
        sql = load_query("task/update_by_id")
        assert "allocated_node_id = :node_id" in sql
        # RETURNING stays task_id only (existence check, not _row_to_task feed)
        assert "RETURNING task_id" in sql

    def test_get_by_id_sql_includes_allocated_node_id(self) -> None:
        sql = load_query("task/get_by_id")
        assert "allocated_node_id" in sql

    def test_list_by_status_sql_includes_allocated_node_id(self) -> None:
        sql = load_query("task/list_by_status")
        assert "allocated_node_id" in sql

    def test_list_by_jobs_sql_includes_allocated_node_id(self) -> None:
        sql = load_query("task/list_by_jobs")
        assert "allocated_node_id" in sql

    def test_update_status_sql_does_not_touch_allocated_node_id(self) -> None:
        sql = load_query("task/update_status")
        assert "allocated_node_id" not in sql

    def test_get_ids_by_ip_and_status_sql_does_not_touch_allocated_node_id(
        self,
    ) -> None:
        sql = load_query("task/get_ids_by_ip_and_status")
        assert "allocated_node_id" not in sql

    def test_count_by_status_sql_does_not_touch_allocated_node_id(self) -> None:
        sql = load_query("task/count_by_status")
        assert "allocated_node_id" not in sql
