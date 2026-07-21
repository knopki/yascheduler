"""Integration tests for apply_schema() against real PostgreSQL."""
# region MODULE_CONTRACT
# PURPOSE: Integration tests for apply_schema() against real PostgreSQL via testcontainers.
# SCOPE: Schema application, idempotency error, connection lifecycle.
# KEYWORDS: apply_schema, idempotency, connection lifecycle
# endregion MODULE_CONTRACT

import logging
from urllib.parse import urlparse

import pytest
from pg8000 import DatabaseError
from testcontainers.postgres import PostgresContainer

from yascheduler.infra.persistence import PostgresDbConfig
from yascheduler.infra.persistence.postgres_schema import apply_schema


def _make_config(pg: PostgresContainer) -> PostgresDbConfig:
    url = urlparse(pg.get_connection_url())
    return PostgresDbConfig(
        user=url.username or "test",
        password=url.password or "test",
        database=url.path.lstrip("/"),
        host=url.hostname or "localhost",
        port=url.port or 5432,
    )


def test_apply_schema_succeeds() -> None:
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)


def test_apply_schema_tables_exist() -> None:
    from pg8000.native import Connection

    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)

        conn = Connection(
            user=config.user,
            host=config.host,
            database=config.database,
            port=config.port,
            password=config.password,
        )
        rows = conn.run("SELECT COUNT(*) FROM yascheduler_nodes")
        conn.close()
        assert rows[0][0] == 0


def test_apply_schema_raises_on_existing(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _strict_schema = (
        "CREATE TABLE yascheduler_nodes ("
        "ip VARCHAR(15) UNIQUE, "
        "port INTEGER DEFAULT 22, "
        "username VARCHAR(255) DEFAULT 'root', "
        "ncpus SMALLINT DEFAULT NULL, "
        "enabled BOOLEAN DEFAULT TRUE, "
        "cloud VARCHAR(32) DEFAULT NULL); "
        "CREATE TABLE yascheduler_tasks ("
        "task_id SERIAL PRIMARY KEY, "
        "label VARCHAR(256), "
        "metadata JSONB, "
        "ip VARCHAR(15), "
        "status SMALLINT);"
    )
    monkeypatch.setattr(
        "yascheduler.infra.persistence.postgres_schema.load_query",
        lambda name: _strict_schema,
    )

    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)

        with caplog.at_level(logging.ERROR), pytest.raises(DatabaseError):
            apply_schema(config)

    assert any(
        "Database already initialized!" in r.getMessage() for r in caplog.records
    )


def test_apply_schema_has_node_ncpus_positive_check() -> None:
    from pg8000.native import Connection

    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)

        conn = Connection(
            user=config.user,
            host=config.host,
            database=config.database,
            port=config.port,
            password=config.password,
        )
        try:
            # Assert node_ncpus_positive CHECK exists
            conn.run("BEGIN")
            try:
                rows = conn.run(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_name = 'yascheduler_nodes' "
                    "AND constraint_type = 'CHECK' "
                    "AND constraint_name = 'node_ncpus_positive'",
                )
            finally:
                conn.run("ROLLBACK")
            assert len(rows) == 1, (
                "fresh DB must have node_ncpus_positive CHECK constraint"
            )

            # Assert ncpus column is nullable SMALLINT DEFAULT NULL
            conn.run("BEGIN")
            try:
                rows = conn.run(
                    "SELECT is_nullable, column_default, data_type "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'yascheduler_nodes' "
                    "AND column_name = 'ncpus'",
                )
            finally:
                conn.run("ROLLBACK")
            assert len(rows) == 1, "ncpus column must exist"
            assert rows[0][0] == "YES", (
                f"ncpus should be nullable, got is_nullable={rows[0][0]}"
            )
            # column_default should contain 'NULL' (PostgreSQL default default)
            # or be None (no explicit default means nullable).
            assert rows[0][2] == "smallint", (
                f"ncpus should be smallint, got {rows[0][2]}"
            )
        finally:
            conn.close()
