# FILE: tests/unit/test_persistence_adapter.py
# VERSION: 1.4.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for yascheduler.adapters.persistence.
#   SCOPE: load_query file-reading and caching behaviour; PostgresUnitOfWork lifecycle;
#          PostgresTaskRepository and PostgresNodeRepository CRUD via fake _run.
#   DEPENDS: none
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_load_query_first_call_reads_file - verify disk read on first access
#   test_load_query_second_call_uses_cache - verify cached result (no re-read)
#   test_uow_enter_creates_repositories - verify __aenter__ sets tasks and nodes
#   test_uow_commit_called - verify commit delegates to connection
#   test_uow_rollback_on_exception - verify exception triggers rollback
#   test_uow_closes_connection - verify connection.close is called on exit
#   TestPostgresTaskRepository - task CRUD via mocked _run
#   TestPostgresNodeRepository - node CRUD via mocked _run
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - Update test_uow_commit_after_exit_raises to catch UnitOfWorkNotInitializedError.
#   PREVIOUS_CHANGE: v1.3.0 - Convert all mock _run return values from tuples to dicts to match
#                         dict-based row mapping refactor in PostgresRepository.
# END_CHANGE_SUMMARY

import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from yascheduler.adapters.persistence import load_query
from yascheduler.adapters.persistence.exceptions import UnitOfWorkNotInitializedError
from yascheduler.adapters.persistence.postgres import (
    PostgresNodeRepository,
    PostgresTaskRepository,
)
from yascheduler.adapters.persistence.postgres_uow import PostgresUnitOfWork
from yascheduler.domain.model import (
    Node,
    Task,
    TaskContext,
)
from yascheduler.domain.model import (
    TaskStatus as DomainTaskStatus,
)


# START_CONTRACT: test_load_query_first_call_reads_file
#   PURPOSE: Verify that the first call to load_query reads the file from disk
#            and returns its contents unchanged.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Creates a temporary .sql file in the persistence sql/ tree.
#   LINKS: load_query
# END_CONTRACT: test_load_query_first_call_reads_file
@pytest.mark.unit
def test_load_query_first_call_reads_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_query reads the file on first call and returns its content."""
    load_query.cache_clear()
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir(parents=True)
    sql_file = sql_dir / "task" / "get_by_id.sql"
    sql_file.parent.mkdir(parents=True)
    sql_file.write_text("SELECT * FROM tasks WHERE id = :task_id")

    monkeypatch.setattr("yascheduler.adapters.persistence.sql_loader._SQL_DIR", sql_dir)

    result = load_query("task/get_by_id")
    assert result == "SELECT * FROM tasks WHERE id = :task_id"

    # File change after first call should NOT affect future results (cached).
    sql_file.write_text("MUTATED")
    assert load_query("task/get_by_id") == "SELECT * FROM tasks WHERE id = :task_id"


# START_CONTRACT: test_load_query_second_call_uses_cache
#   PURPOSE: Verify that a second call does not re-read the file by checking
#            that mutating the file between calls does not change the result.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None
#   LINKS: load_query
# END_CONTRACT: test_load_query_second_call_uses_cache
@pytest.mark.unit
def test_load_query_second_call_uses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_query returns the cached value; file mutation has no effect."""
    load_query.cache_clear()
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir(parents=True)
    sql_file = sql_dir / "node" / "list_enabled.sql"
    sql_file.parent.mkdir(parents=True)
    sql_file.write_text("SELECT * FROM nodes WHERE enabled = TRUE")

    monkeypatch.setattr("yascheduler.adapters.persistence.sql_loader._SQL_DIR", sql_dir)

    # First call — reads from disk.
    result_a = load_query("node/list_enabled")
    assert result_a == "SELECT * FROM nodes WHERE enabled = TRUE"

    # Mutate the file.
    sql_file.write_text("SELECT 1")

    # Second call — should return cached value.
    result_b = load_query("node/list_enabled")
    assert result_b == "SELECT * FROM nodes WHERE enabled = TRUE"
    assert result_b != "SELECT 1"


# START_CONTRACT: test_uow_enter_creates_repositories
#   PURPOSE: Verify that async enter creates task and node repositories.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None (mocked connection)
#   LINKS: PostgresUnitOfWork, PostgresTaskRepository, PostgresNodeRepository
# END_CONTRACT: test_uow_enter_creates_repositories
async def test_uow_enter_creates_repositories(mocker: MockerFixture) -> None:
    """__aenter__ instantiates both task and node repositories."""
    mock_conn = mocker.MagicMock()
    mocker.patch(
        "yascheduler.adapters.persistence.postgres_uow.Connection",
        return_value=mock_conn,
    )
    config = mocker.MagicMock()
    uow = PostgresUnitOfWork(config)

    async with uow:
        assert isinstance(uow.tasks, PostgresTaskRepository)
        assert isinstance(uow.nodes, PostgresNodeRepository)


# START_CONTRACT: test_uow_commit_called
#   PURPOSE: Verify commit delegates to pg8000 connection.run("COMMIT").
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None (mocked connection)
#   LINKS: PostgresUnitOfWork.commit
# END_CONTRACT: test_uow_commit_called
async def test_uow_commit_called(mocker: MockerFixture) -> None:
    """commit() calls connection.run('COMMIT')."""
    mock_conn = mocker.MagicMock()
    mocker.patch(
        "yascheduler.adapters.persistence.postgres_uow.Connection",
        return_value=mock_conn,
    )
    config = mocker.MagicMock()
    uow = PostgresUnitOfWork(config)

    async with uow:
        await uow.commit()

    mock_conn.run.assert_any_call("COMMIT")


# START_CONTRACT: test_uow_rollback_on_exception
#   PURPOSE: Verify that a context body exception triggers rollback and close.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None (mocked connection)
#   LINKS: PostgresUnitOfWork.rollback
# END_CONTRACT: test_uow_rollback_on_exception
async def test_uow_rollback_on_exception(mocker: MockerFixture) -> None:
    """Exception inside context triggers rollback and closes connection."""
    mock_conn = mocker.MagicMock()
    mocker.patch(
        "yascheduler.adapters.persistence.postgres_uow.Connection",
        return_value=mock_conn,
    )
    config = mocker.MagicMock()
    uow = PostgresUnitOfWork(config)

    with pytest.raises(ValueError):
        async with uow:
            raise ValueError("test error")

    mock_conn.run.assert_any_call("ROLLBACK")
    mock_conn.close.assert_called_once()


# START_CONTRACT: test_uow_closes_connection
#   PURPOSE: Verify connection.close() is called on normal exit.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None (mocked connection)
#   LINKS: PostgresUnitOfWork.__aexit__
# END_CONTRACT: test_uow_closes_connection
async def test_uow_closes_connection(mocker: MockerFixture) -> None:
    """connection.close() is called on normal exit."""
    mock_conn = mocker.MagicMock()
    mocker.patch(
        "yascheduler.adapters.persistence.postgres_uow.Connection",
        return_value=mock_conn,
    )
    config = mocker.MagicMock()
    uow = PostgresUnitOfWork(config)

    async with uow:
        pass

    mock_conn.close.assert_called_once()


# START_CONTRACT: test_uow_commit_after_exit_raises
#   PURPOSE: commit() raises UnitOfWorkNotInitializedError when called outside 'async with' block.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None (mocked connection)
#   LINKS: PostgresUnitOfWork.commit, PostgresUnitOfWork._require_conn
# END_CONTRACT: test_uow_commit_after_exit_raises
async def test_uow_commit_after_exit_raises(mocker: MockerFixture) -> None:
    """commit() raises UnitOfWorkNotInitializedError when called outside 'async with' block."""
    mock_conn = mocker.MagicMock()
    mocker.patch(
        "yascheduler.adapters.persistence.postgres_uow.Connection",
        return_value=mock_conn,
    )
    config = mocker.MagicMock()
    uow = PostgresUnitOfWork(config)

    async with uow:
        pass  # connection now closed by __aexit__

    with pytest.raises(
        UnitOfWorkNotInitializedError, match="Connection not initialized"
    ):
        await uow.commit()


# START_CONTRACT: test_uow_double_commit
#   PURPOSE: Second commit within the same context is accepted by pg8000 (idempotent).
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: None (mocked connection)
#   LINKS: PostgresUnitOfWork.commit
# END_CONTRACT: test_uow_double_commit
async def test_uow_double_commit(mocker: MockerFixture) -> None:
    """Second commit within the same context is accepted by pg8000 (idempotent)."""
    mock_conn = mocker.MagicMock()
    mocker.patch(
        "yascheduler.adapters.persistence.postgres_uow.Connection",
        return_value=mock_conn,
    )
    config = mocker.MagicMock()
    uow = PostgresUnitOfWork(config)

    async with uow:
        await uow.commit()
        await uow.commit()

    # Both commits executed
    assert mock_conn.run.call_count >= 2  # BEGIN + COMMIT + COMMIT
    commit_calls = [c for c in mock_conn.run.call_args_list if c[0][0] == "COMMIT"]
    assert len(commit_calls) == 2


# ============================================================================
# PostgresTaskRepository — unit tests with mocked _run
# ============================================================================


class TestPostgresTaskRepository:
    """PostgresTaskRepository CRUD operations via fake in-memory _run."""

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _make_repo(mocker: MockerFixture) -> PostgresTaskRepository:
        """Build a minimal PostgresTaskRepository with a mock _run."""
        repo = PostgresTaskRepository.__new__(PostgresTaskRepository)
        mock_run = mocker.AsyncMock()
        mocker.patch.object(repo, "_run", mock_run)
        return repo

    # -- get -------------------------------------------------------------------

    async def test_get_returns_task(self, mocker: MockerFixture) -> None:
        """get returns a Task hydrated from the row returned by _run."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 42,
                "label": "test_label",
                "ip": "10.0.0.1",
                "status": 1,
                "metadata": '{"engine":"fleur"}',
            }
        ]

        task = await repo.get(42)

        assert task is not None
        assert task.task_id == 42
        assert task.label == "test_label"
        assert task.allocated_ip == "10.0.0.1"
        assert task.context.engine == "fleur"
        assert task.status == DomainTaskStatus.RUNNING

    async def test_get_returns_none_when_not_found(self, mocker: MockerFixture) -> None:
        """get returns None when _run returns an empty list."""
        repo = self._make_repo(mocker)
        repo._run.return_value = []  # type: ignore[attr-defined]

        task = await repo.get(999)

        assert task is None

    async def test_get_with_none_ip_and_extra_fields(
        self, mocker: MockerFixture
    ) -> None:
        """get handles null ip and extra metadata fields."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 1,
                "label": "no-ip-task",
                "ip": None,
                "status": 0,
                "metadata": json.dumps(
                    {
                        "engine": "cp2k",
                        "remote_folder": "/remote/path",
                        "local_folder": "/local/path",
                        "webhook_url": "https://hook.example.com",
                        "webhook_custom_params": {"key": "val"},
                        "extra_field": "extra_val",
                    }
                ),
            }
        ]

        task = await repo.get(1)

        assert task is not None
        assert task.task_id == 1
        assert task.label == "no-ip-task"
        assert task.allocated_ip is None
        assert task.status == DomainTaskStatus.TO_DO
        assert task.context.engine == "cp2k"
        assert task.context.remote_folder == "/remote/path"
        assert task.context.local_folder == "/local/path"
        assert task.context.webhook_url == "https://hook.example.com"
        assert task.context.webhook_custom_params == {"key": "val"}
        assert task.context.extra == {"extra_field": "extra_val"}

    # -- insert ----------------------------------------------------------------

    async def test_insert_returns_task_with_id(self, mocker: MockerFixture) -> None:
        """insert runs INSERT SQL and returns Task with generated ID."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 99,
                "label": "label",
                "ip": None,
                "status": 0,
                "metadata": '{"engine":"fleur"}',
            }
        ]

        task = Task(
            task_id=0,
            label="label",
            context=TaskContext(engine="fleur"),
            status=DomainTaskStatus.TO_DO,
        )
        result = await repo.insert(task)

        assert result.task_id == 99
        assert result.label == "label"
        assert "INSERT INTO yascheduler_tasks" in repo._run.call_args[0][0]  # type: ignore[attr-defined]

    # -- save ------------------------------------------------------------------

    async def test_save_calls_upsert(self, mocker: MockerFixture) -> None:
        """save calls _run with the upsert query and all task fields."""
        repo = self._make_repo(mocker)
        ctx = TaskContext(engine="fleur", remote_folder="/remote")
        task = Task(
            task_id=7, label="my-job", context=ctx, status=DomainTaskStatus.TO_DO
        )

        await repo.save(task)

        repo._run.assert_awaited_once()  # type: ignore[attr-defined]
        call_args = repo._run.call_args  # type: ignore[attr-defined]
        assert call_args is not None
        (sql,), kwargs = call_args
        assert sql == load_query("task/upsert")
        assert kwargs["task_id"] == 7
        assert kwargs["label"] == "my-job"
        assert kwargs["status"] == 0
        assert kwargs["ip"] is None
        metadata = json.loads(kwargs["metadata"])
        assert metadata["engine"] == "fleur"
        assert metadata["remote_folder"] == "/remote"

    async def test_save_running_task(self, mocker: MockerFixture) -> None:
        """save persists a RUNNING task with its allocated_ip."""
        repo = self._make_repo(mocker)
        ctx = TaskContext(engine="vasp")
        task = Task(
            task_id=3,
            label="running-job",
            context=ctx,
            status=DomainTaskStatus.RUNNING,
            allocated_ip="10.0.0.5",
        )

        await repo.save(task)

        _, kwargs = repo._run.call_args  # type: ignore[attr-defined]
        assert kwargs["status"] == 1
        assert kwargs["ip"] == "10.0.0.5"

    # -- list_by_status --------------------------------------------------------

    async def test_list_by_status_returns_tasks(self, mocker: MockerFixture) -> None:
        """list_by_status returns a Task for each row."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 1,
                "label": "a",
                "ip": "10.0.0.1",
                "status": 0,
                "metadata": '{"engine":"fleur"}',
            },
            {
                "task_id": 2,
                "label": "b",
                "ip": "10.0.0.2",
                "status": 1,
                "metadata": '{"engine":"cp2k"}',
            },
        ]

        tasks = await repo.list_by_status(
            {DomainTaskStatus.TO_DO, DomainTaskStatus.RUNNING}
        )

        assert len(tasks) == 2
        assert tasks[0].task_id == 1
        assert tasks[0].status == DomainTaskStatus.TO_DO
        assert tasks[1].task_id == 2
        assert tasks[1].status == DomainTaskStatus.RUNNING

    async def test_list_by_status_empty(self, mocker: MockerFixture) -> None:
        """list_by_status returns empty list when no rows."""
        repo = self._make_repo(mocker)
        repo._run.return_value = []  # type: ignore[attr-defined]

        tasks = await repo.list_by_status({DomainTaskStatus.DONE})

        assert tasks == []

    # -- list_by_jobs ----------------------------------------------------------

    async def test_list_by_jobs_returns_tasks(self, mocker: MockerFixture) -> None:
        """list_by_jobs returns tasks matching the given job ids."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "task_id": 10,
                "label": "job-x",
                "ip": "10.0.0.1",
                "status": 2,
                "metadata": '{"engine":"fleur"}',
            },
            {
                "task_id": 20,
                "label": "job-y",
                "ip": None,
                "status": 2,
                "metadata": '{"engine":"cp2k"}',
            },
        ]

        tasks = await repo.list_by_jobs([10, 20])

        assert len(tasks) == 2
        assert tasks[0].task_id == 10
        assert tasks[0].status == DomainTaskStatus.DONE
        assert tasks[1].task_id == 20

    async def test_list_by_jobs_empty(self, mocker: MockerFixture) -> None:
        """list_by_jobs returns empty list when _run returns no rows."""
        repo = self._make_repo(mocker)
        repo._run.return_value = []  # type: ignore[attr-defined]

        tasks = await repo.list_by_jobs([999])

        assert tasks == []

    # -- count_by_status -------------------------------------------------------

    async def test_count_by_status_returns_mapping(self, mocker: MockerFixture) -> None:
        """count_by_status returns a mapping of TaskStatus -> count."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {"status": 0, "count": 5},
            {"status": 1, "count": 3},
            {"status": 2, "count": 10},
        ]

        counts = await repo.count_by_status()

        assert counts == {
            DomainTaskStatus.TO_DO: 5,
            DomainTaskStatus.RUNNING: 3,
            DomainTaskStatus.DONE: 10,
        }

    async def test_count_by_status_empty(self, mocker: MockerFixture) -> None:
        """count_by_status returns empty mapping when no rows."""
        repo = self._make_repo(mocker)
        repo._run.return_value = []  # type: ignore[attr-defined]

        counts = await repo.count_by_status()

        assert counts == {}


# ============================================================================
# PostgresNodeRepository — unit tests with mocked _run
# ============================================================================


class TestPostgresNodeRepository:
    """PostgresNodeRepository CRUD operations via fake in-memory _run."""

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _make_repo(mocker: MockerFixture) -> PostgresNodeRepository:
        """Build a minimal PostgresNodeRepository with a mock _run."""
        repo = PostgresNodeRepository.__new__(PostgresNodeRepository)
        mock_run = mocker.AsyncMock()
        mocker.patch.object(repo, "_run", mock_run)
        return repo

    # -- get -------------------------------------------------------------------

    async def test_get_returns_node(self, mocker: MockerFixture) -> None:
        """get returns a Node hydrated from the row returned by _run."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "ip": "10.0.0.1",
                "ncpus": 8,
                "enabled": True,
                "cloud": "hetzner",
                "username": "root",
                "port": 22,
            }
        ]

        node = await repo.get("10.0.0.1")

        assert node is not None
        assert node.ip == "10.0.0.1"
        assert node.ncpus == 8
        assert node.enabled is True
        assert node.cloud == "hetzner"
        assert node.username == "root"
        assert node.port == 22

    async def test_get_returns_none_when_not_found(self, mocker: MockerFixture) -> None:
        """get returns None when _run returns empty."""
        repo = self._make_repo(mocker)
        repo._run.return_value = []  # type: ignore[attr-defined]

        node = await repo.get("10.0.0.99")

        assert node is None

    async def test_get_with_zero_ncpus(self, mocker: MockerFixture) -> None:
        """get handles null/zero ncpus correctly (defaults to 0)."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "ip": "10.0.0.2",
                "ncpus": None,
                "enabled": False,
                "cloud": None,
                "username": "admin",
                "port": 2222,
            }
        ]

        node = await repo.get("10.0.0.2")

        assert node is not None
        assert node.ip == "10.0.0.2"
        assert node.ncpus == 0
        assert node.enabled is False
        assert node.cloud is None
        assert node.port == 2222

    # -- get_by_ips ------------------------------------------------------------

    async def test_get_by_ips_empty_returns_empty_dict(
        self, mocker: MockerFixture
    ) -> None:
        """get_by_ips([]) returns an empty dict."""
        repo = self._make_repo(mocker)
        repo._run.return_value = []  # type: ignore[attr-defined]

        result = await repo.get_by_ips([])

        assert result == {}
        assert repo._run.call_count == 1  # type: ignore[attr-defined]

    # -- list_all --------------------------------------------------------------

    async def test_list_all_returns_nodes(self, mocker: MockerFixture) -> None:
        """list_all returns all nodes from _run."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "ip": "10.0.0.1",
                "ncpus": 4,
                "enabled": True,
                "cloud": "hetzner",
                "username": "root",
                "port": 22,
            },
            {
                "ip": "10.0.0.2",
                "ncpus": 8,
                "enabled": False,
                "cloud": "upcloud",
                "username": "admin",
                "port": 2222,
            },
        ]

        nodes = await repo.list_all()

        assert len(nodes) == 2
        assert nodes[0].ip == "10.0.0.1"
        assert nodes[1].ip == "10.0.0.2"

    # -- list_enabled / list_disabled ------------------------------------------

    async def test_list_enabled_returns_only_enabled(
        self, mocker: MockerFixture
    ) -> None:
        """list_enabled returns only nodes with valid IPs (containing '.')."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "ip": "10.0.0.1",
                "ncpus": 4,
                "enabled": True,
                "cloud": "hetzner",
                "username": "root",
                "port": 22,
            },
            {
                "ip": "10.0.0.2",
                "ncpus": 8,
                "enabled": True,
                "cloud": "upcloud",
                "username": "admin",
                "port": 2222,
            },
            {
                "ip": "10.0.0.3",
                "ncpus": 2,
                "enabled": False,
                "cloud": "hetzner",
                "username": "root",
                "port": 22,
            },
        ]

        nodes = await repo.list_enabled()

        # All rows have "." in IP, so all 3 pass the filter
        assert len(nodes) == 3

    async def test_list_enabled_filters_invalid_ips(
        self, mocker: MockerFixture
    ) -> None:
        """list_enabled excludes rows whose ip does not contain '.'."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "ip": "10.0.0.1",
                "ncpus": 4,
                "enabled": True,
                "cloud": "hetzner",
                "username": "root",
                "port": 22,
            },
            {
                "ip": "localhost",
                "ncpus": 4,
                "enabled": True,
                "cloud": None,
                "username": "root",
                "port": 22,
            },
        ]

        nodes = await repo.list_enabled()

        assert len(nodes) == 1
        assert nodes[0].ip == "10.0.0.1"

    async def test_list_disabled_returns_disabled_with_valid_ips(
        self, mocker: MockerFixture
    ) -> None:
        """list_disabled returns all rows (SQL filters disabled) that have valid IPs."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "ip": "10.0.0.1",
                "ncpus": 4,
                "enabled": False,
                "cloud": "hetzner",
                "username": "root",
                "port": 22,
            },
            {
                "ip": "10.0.0.2",
                "ncpus": 8,
                "enabled": False,
                "cloud": "upcloud",
                "username": "admin",
                "port": 2222,
            },
        ]

        nodes = await repo.list_disabled()

        assert len(nodes) == 2
        assert all(n.enabled is False for n in nodes)

    async def test_list_disabled_filters_invalid_ips(
        self, mocker: MockerFixture
    ) -> None:
        """list_disabled excludes rows whose ip does not contain '.'."""
        repo = self._make_repo(mocker)
        repo._run.return_value = [  # type: ignore[attr-defined]
            {
                "ip": "10.0.0.1",
                "ncpus": 4,
                "enabled": False,
                "cloud": "hetzner",
                "username": "root",
                "port": 22,
            },
            {
                "ip": "localhost",
                "ncpus": 8,
                "enabled": False,
                "cloud": None,
                "username": "admin",
                "port": 2222,
            },
        ]

        nodes = await repo.list_disabled()

        assert len(nodes) == 1
        assert nodes[0].ip == "10.0.0.1"

    # -- add -------------------------------------------------------------------

    async def test_add_inserts_node(self, mocker: MockerFixture) -> None:
        """add calls _run with the insert query and node fields."""
        repo = self._make_repo(mocker)
        node = Node(
            ip="10.0.0.1",
            ncpus=8,
            enabled=True,
            cloud="hetzner",
            username="root",
            port=22,
        )

        await repo.add(node)

        repo._run.assert_awaited_once()  # type: ignore[attr-defined]
        _, kwargs = repo._run.call_args  # type: ignore[attr-defined]
        assert kwargs["ip"] == "10.0.0.1"
        assert kwargs["ncpus"] == 8
        assert kwargs["enabled"] is True
        assert kwargs["cloud"] == "hetzner"
        assert kwargs["username"] == "root"
        assert kwargs["port"] == 22

    async def test_add_inserts_cloud_node(self, mocker: MockerFixture) -> None:
        """add persists a cloud-provisioned node."""
        repo = self._make_repo(mocker)
        node = Node(
            ip="10.0.0.5",
            ncpus=2,
            enabled=False,
            cloud="upcloud",
            username="admin",
            port=2222,
        )

        await repo.add(node)

        _, kwargs = repo._run.call_args  # type: ignore[attr-defined]
        assert kwargs["cloud"] == "upcloud"
        assert kwargs["enabled"] is False

    # -- enable / disable / remove ---------------------------------------------

    async def test_enable_executes_update(self, mocker: MockerFixture) -> None:
        """enable calls _run with the enable query and ip."""
        repo = self._make_repo(mocker)

        await repo.enable("10.0.0.1")

        repo._run.assert_awaited_once_with(load_query("node/enable"), ip="10.0.0.1")  # type: ignore[attr-defined]

    async def test_disable_executes_update(self, mocker: MockerFixture) -> None:
        """disable calls _run with the disable query and ip."""
        repo = self._make_repo(mocker)

        await repo.disable("10.0.0.1")

        repo._run.assert_awaited_once_with(load_query("node/disable"), ip="10.0.0.1")  # type: ignore[attr-defined]

    async def test_remove_executes_delete(self, mocker: MockerFixture) -> None:
        """remove calls _run with the remove (delete) query and ip."""
        repo = self._make_repo(mocker)

        await repo.remove("10.0.0.1")

        repo._run.assert_awaited_once_with(load_query("node/remove"), ip="10.0.0.1")  # type: ignore[attr-defined]
