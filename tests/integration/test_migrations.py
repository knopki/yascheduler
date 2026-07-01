# FILE: tests/integration/test_migrations.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for the migration runner against real PostgreSQL via testcontainers.
#   SCOPE: Fresh/legacy/modern DB cohorts; .py best-effort reopen; .sql failure rollback.
#   DEPENDS: M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATION-BASE
#   LINKS: M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-SCHEMA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _make_config - build PostgresDbConfig from a PostgresContainer connection URL
#   _tracker_rows - read migration_id rows from yascheduler_migrations within a rolled-back read
#   _columns - read column names of a table within a rolled-back read
#   test_fresh_db_seeds_last_and_skips_migrations - fresh DB seeded to last_migration; apply_migrations no-op
#   test_legacy_db_runs_all_migrations - legacy DB (nodes, no tracker) runs all migrations
#   test_modern_db_skips_bootstrap_and_applies_only_pending - modern DB applies only prefix_id > last
#   test_py_migration_best_effort_reopen - .py migration closing its txn is still recorded
#   test_sql_migration_failure_rolls_back_and_not_recorded - .sql failure rolls back, not recorded
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial integration tests for apply_migrations (add-db-migrations).
# END_CHANGE_SUMMARY

"""Integration tests for the migration runner against real PostgreSQL.

Each test starts a fresh PostgresContainer so the three DB cohorts (fresh,
legacy, modern) can be set up independently. Tests 7.4/7.5 use a temp
migrations directory so synthetic migration files do not pollute the real
``sql/migrations/`` shipped with the package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pg8000.native
import pytest
from pg8000 import DatabaseError
from testcontainers.postgres import PostgresContainer

from yascheduler.infra.persistence import PostgresDbConfig, apply_migrations
from yascheduler.infra.persistence.postgres_schema import apply_schema

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _make_config(pg: PostgresContainer) -> PostgresDbConfig:
    url = urlparse(pg.get_connection_url())
    return PostgresDbConfig(
        user=url.username or "test",
        password=url.password or "test",
        database=url.path.lstrip("/"),
        host=url.hostname or "localhost",
        port=url.port or 5432,
    )


def _connect(config: PostgresDbConfig) -> pg8000.native.Connection:
    return pg8000.native.Connection(
        user=config.user,
        host=config.host,
        database=config.database,
        port=config.port,
        password=config.password,
    )


def _tracker_rows(conn: pg8000.native.Connection) -> list[str]:
    """Return migration_id rows from yascheduler_migrations (read in a rolled-back txn)."""
    conn.run("BEGIN")
    try:
        rows = conn.run(
            "SELECT migration_id FROM yascheduler_migrations ORDER BY migration_id"
        )
    finally:
        conn.run("ROLLBACK")
    return [r[0] for r in rows]


def _columns(conn: pg8000.native.Connection, table: str) -> list[str]:
    conn.run("BEGIN")
    try:
        rows = conn.run(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY column_name",
            t=table,
        )
    finally:
        conn.run("ROLLBACK")
    return [r[0] for r in rows]


def _table_exists(conn: pg8000.native.Connection, table: str) -> bool:
    conn.run("BEGIN")
    try:
        rows = conn.run("SELECT to_regclass(:t)", t=table)
    finally:
        conn.run("ROLLBACK")
    return rows[0][0] is not None


# START_CONTRACT: test_fresh_db_seeds_last_and_skips_migrations
#   PURPOSE: On a fresh DB, apply_schema seeds the tracker to last_migration; apply_migrations applies nothing further.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; applies schema + migrations
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_fresh_db_seeds_last_and_skips_migrations
def test_fresh_db_seeds_last_and_skips_migrations() -> None:
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)

        conn = _connect(config)
        try:
            seeded = _tracker_rows(conn)
            assert seeded == ["001"]
            assert {"username", "port"} <= set(_columns(conn, "yascheduler_nodes"))
        finally:
            conn.close()

        apply_migrations(config)

        conn = _connect(config)
        try:
            assert _tracker_rows(conn) == ["001"]
        finally:
            conn.close()


# START_CONTRACT: test_legacy_db_runs_all_migrations
#   PURPOSE: On a legacy DB (yascheduler_nodes present, no tracker), apply_schema creates an empty tracker; apply_migrations runs all migrations.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; applies schema + migrations
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_legacy_db_runs_all_migrations
def test_legacy_db_runs_all_migrations() -> None:
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)

        conn = _connect(config)
        try:
            conn.run("CREATE TABLE yascheduler_nodes (ip VARCHAR(15) UNIQUE)")
        finally:
            conn.close()

        apply_schema(config)

        conn = _connect(config)
        try:
            assert _tracker_rows(conn) == []
        finally:
            conn.close()

        apply_migrations(config)

        conn = _connect(config)
        try:
            assert _tracker_rows(conn) == ["001"]
            assert {"username", "port"} <= set(_columns(conn, "yascheduler_nodes"))
        finally:
            conn.close()


# START_CONTRACT: test_modern_db_skips_bootstrap_and_applies_only_pending
#   PURPOSE: On a modern DB (tracker + nodes, MAX='000'), apply_schema is a no-op and apply_migrations applies only prefix_id > '000' (i.e. '001').
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; applies schema + migrations
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_modern_db_skips_bootstrap_and_applies_only_pending
def test_modern_db_skips_bootstrap_and_applies_only_pending() -> None:
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)

        conn = _connect(config)
        try:
            conn.run(
                "CREATE TABLE yascheduler_migrations "
                "(migration_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            conn.run("CREATE TABLE yascheduler_nodes (ip VARCHAR(15) UNIQUE)")
            conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES ('000')")
        finally:
            conn.close()

        apply_schema(config)

        conn = _connect(config)
        try:
            assert _tracker_rows(conn) == ["000"]
        finally:
            conn.close()

        apply_migrations(config)

        conn = _connect(config)
        try:
            assert _tracker_rows(conn) == ["000", "001"]
            assert {"username", "port"} <= set(_columns(conn, "yascheduler_nodes"))
        finally:
            conn.close()


# START_CONTRACT: test_py_migration_best_effort_reopen
#   PURPOSE: A .py migration that closes its transaction via self.commit() is still recorded; its work is committed.
#   INPUTS: { tmp_path: Path, monkeypatch }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; applies schema + a synthetic migration from a temp dir
#   LINKS: M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-MIGRATION-BASE
# END_CONTRACT: test_py_migration_best_effort_reopen
def test_py_migration_best_effort_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "002_reopen.py").write_text(
        "from yascheduler.infra.persistence.migration_base import Migration\n"
        "class Reopen(Migration):\n"
        "    def migrate(self) -> None:\n"
        "        self.commit()\n"
        "        self.conn.run('CREATE TABLE test_reopen (id int)')\n"
    )
    monkeypatch.setattr(
        "yascheduler.infra.persistence.postgres_migrations._MIGRATIONS_DIR",
        migrations_dir,
    )

    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)
        apply_migrations(config)

        conn = _connect(config)
        try:
            assert _tracker_rows(conn) == ["001", "002"]
            assert _table_exists(conn, "test_reopen")
        finally:
            conn.close()


# START_CONTRACT: test_sql_migration_failure_rolls_back_and_not_recorded
#   PURPOSE: A failing .sql migration rolls back (no partial table) and is not recorded in the tracker.
#   INPUTS: { tmp_path: Path, monkeypatch }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; applies schema + a synthetic failing migration from a temp dir
#   LINKS: M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_sql_migration_failure_rolls_back_and_not_recorded
def test_sql_migration_failure_rolls_back_and_not_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "002_fail.sql").write_text(
        "CREATE TABLE fail_tbl (id int); CREATE TABLE fail_tbl (id int);"
    )
    monkeypatch.setattr(
        "yascheduler.infra.persistence.postgres_migrations._MIGRATIONS_DIR",
        migrations_dir,
    )

    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)

        with pytest.raises(DatabaseError):
            apply_migrations(config)

        conn = _connect(config)
        try:
            assert "002" not in _tracker_rows(conn)
            assert not _table_exists(conn, "fail_tbl")
        finally:
            conn.close()
