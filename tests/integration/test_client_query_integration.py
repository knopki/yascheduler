# FILE: tests/integration/test_client_query_integration.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Implementation-agnostic integration test pinning the Yascheduler query-method output shape against real PostgreSQL.
#   SCOPE: Submit a real task, query via jobs=[id] and status=[0], assert 6-key dict shape.
#   DEPENDS: M-CLIENT, M-CONFIG, M-DB, M-PERSISTENCE-SCHEMA
#   LINKS: M-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _query_config - session-scoped INI path pointing at testcontainer DB with minimal engine
#   test_query_by_jobs - queue_get_tasks(jobs=[id]) returns one 6-key Mapping
#   test_query_by_status - queue_get_tasks(status=[0]) returns matching 6-key Mapping
#   test_query_single_task - queue_get_task(id) returns Mapping; unknown id returns None
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial implementation-agnostic integration test for client query path (client-query-uow).
# END_CHANGE_SUMMARY

"""Implementation-agnostic integration test — Yascheduler query path against real PostgreSQL.

Implementation-agnostic: asserts observable behavior only (never isinstance
on db.TaskStatus). Valid both before the UoW swap (DB-backed) and after.
"""

from typing import TYPE_CHECKING

import pytest

from yascheduler.client import Yascheduler

if TYPE_CHECKING:
    from collections.abc import Iterator

    from yascheduler.config import ConfigDb

EXPECTED_KEYS = {"task_id", "label", "ip", "status", "metadata", "cloud"}


# START_CONTRACT: _query_config
#   PURPOSE: Build an INI config pointing at the testcontainer DB with a minimal engine.
#   INPUTS: { _db_config: ConfigDb, tmp_path_factory: TempPathFactory }
#   OUTPUTS: { Iterator[str] - path to the written INI file }
#   SIDE_EFFECTS: Writes a temp INI file and engine directories.
#   LINKS: M-CONFIG
# END_CONTRACT: _query_config
@pytest.fixture(scope="session")
def _query_config(
    _db_config: "ConfigDb",
    tmp_path_factory: pytest.TempPathFactory,
) -> "Iterator[str]":
    tmp = tmp_path_factory.mktemp("query_config")
    engines_dir = tmp / "data" / "engines" / "test_query"
    engines_dir.mkdir(parents=True)

    db_cfg = _db_config
    ini_path = tmp / "yascheduler.conf"
    ini_path.write_text(
        f"[db]\n"
        f"host = {db_cfg.host}\n"
        f"port = {db_cfg.port}\n"
        f"user = {db_cfg.user}\n"
        f"password = {db_cfg.password}\n"
        f"database = {db_cfg.database}\n"
        f"\n"
        f"[local]\n"
        f"data_dir = {tmp / 'data'}\n"
        f"\n"
        f"[remote]\n"
        f"user = test\n"
        f"\n"
        f"[engine.test_query]\n"
        f"spawn = {{engine_path}}/run.sh\n"
        f"check_pname = sleep\n"
        f"input_files = 1.input\n"
        f"output_files = 1.input.out\n"
        f"platforms = linux\n"
    )
    yield str(ini_path)


# START_CONTRACT: _submit_task
#   PURPOSE: Submit a real TO_DO task via the facade and return its id.
#   INPUTS: { _query_config: str, _init_schema: None }
#   OUTPUTS: { int - task_id }
#   SIDE_EFFECTS: Inserts a task row into the testcontainer PostgreSQL.
#   LINKS: M-CLIENT
# END_CONTRACT: _submit_task
@pytest.fixture
def _submit_task(
    _query_config: str,
    _init_schema: None,
) -> int:
    task_id = Yascheduler(_query_config).queue_submit_task(
        label="gamma-query-test",
        metadata={"1.input": "hello"},
        engine_name="test_query",
    )
    assert task_id > 0
    return task_id


class TestClientQueryIntegration:
    """Implementation-agnostic: query methods return 6-key Mapping shape against real Postgres."""

    def test_query_by_jobs_returns_six_key_mapping(
        self, _query_config: str, _submit_task: int
    ) -> None:
        task_id = _submit_task
        result = Yascheduler(_query_config).queue_get_tasks(jobs=[task_id])

        assert isinstance(result, list)
        assert len(result) == 1
        mapping = result[0]
        assert set(mapping.keys()) == EXPECTED_KEYS
        assert mapping["task_id"] == task_id
        assert mapping["label"] == "gamma-query-test"
        assert int(mapping["status"]) == 0
        assert mapping["status"].name == "TO_DO"
        assert mapping["ip"] == ""
        assert mapping["cloud"] is None
        assert isinstance(mapping["metadata"], dict)

    def test_query_by_status_returns_six_key_mapping(
        self, _query_config: str, _submit_task: int
    ) -> None:
        task_id = _submit_task
        result = Yascheduler(_query_config).queue_get_tasks(status=[0])

        assert isinstance(result, list)
        matching = [m for m in result if m["task_id"] == task_id]
        assert len(matching) == 1
        mapping = matching[0]
        assert set(mapping.keys()) == EXPECTED_KEYS
        assert mapping["status"] == 0
        assert mapping["cloud"] is None

    def test_query_single_task_returns_mapping_or_none(
        self, _query_config: str, _submit_task: int
    ) -> None:
        task_id = _submit_task
        found = Yascheduler(_query_config).queue_get_task(task_id)

        assert found is not None
        assert set(found.keys()) == EXPECTED_KEYS
        assert found["task_id"] == task_id

        unknown = Yascheduler(_query_config).queue_get_task(9_999_999)
        assert unknown is None
