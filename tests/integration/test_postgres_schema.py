# FILE: tests/integration/test_postgres_schema.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for apply_schema() against real PostgreSQL via testcontainers.
#   SCOPE: Schema application, idempotency error, connection lifecycle.
#   DEPENDS: M-PERSISTENCE-SCHEMA, M-CONFIG-DB
#   LINKS: M-PERSISTENCE-SCHEMA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_apply_schema_succeeds - schema applies cleanly on empty database
#   test_apply_schema_tables_exist - tables are queryable after apply_schema
#   test_apply_schema_raises_on_existing - DatabaseError on duplicate application
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial integration tests for apply_schema().
# END_CHANGE_SUMMARY

"""Integration tests for apply_schema() against real PostgreSQL."""

from urllib.parse import urlparse

import pytest
from pg8000 import DatabaseError
from testcontainers.postgres import PostgresContainer

from yascheduler.config.db import ConfigDb
from yascheduler.infra.persistence.postgres_schema import apply_schema


def _make_config(pg: PostgresContainer) -> ConfigDb:
    url = urlparse(pg.get_connection_url())
    return ConfigDb(
        user=url.username or "test",
        password=url.password or "test",
        database=url.path.lstrip("/"),
        host=url.hostname or "localhost",
        port=url.port or 5432,
    )


# START_CONTRACT: test_apply_schema_succeeds
#   PURPOSE: Verify apply_schema() succeeds against an empty PostgreSQL database.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Creates tables in testcontainers PostgreSQL
#   LINKS: M-PERSISTENCE-SCHEMA
# END_CONTRACT: test_apply_schema_succeeds
def test_apply_schema_succeeds() -> None:
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)


# START_CONTRACT: test_apply_schema_tables_exist
#   PURPOSE: Verify tables are queryable after apply_schema().
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Creates tables in testcontainers PostgreSQL
#   LINKS: M-PERSISTENCE-SCHEMA
# END_CONTRACT: test_apply_schema_tables_exist
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


# START_CONTRACT: test_apply_schema_raises_on_existing
#   PURPOSE: Verify apply_schema() raises DatabaseError and prints message when tables exist.
#            Uses monkeypatch to replace schema SQL with non-IF-NOT-EXISTS version to trigger
#            the error path, since production schema.sql uses IF NOT EXISTS.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Creates tables in testcontainers PostgreSQL
#   LINKS: M-PERSISTENCE-SCHEMA
# END_CONTRACT: test_apply_schema_raises_on_existing
def test_apply_schema_raises_on_existing(
    capsys: pytest.CaptureFixture[str],
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

        with pytest.raises(DatabaseError):
            apply_schema(config)

        captured = capsys.readouterr()
        assert "Database already initialized!" in captured.out
