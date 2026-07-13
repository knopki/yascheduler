# FILE: tests/integration/test_migrations.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for the migration runner against real PostgreSQL via testcontainers.
#   SCOPE: Fresh/legacy/modern DB cohorts; .py best-effort reopen; .sql failure rollback; migration 002 backfills node_id SERIAL; migration 010 extracts typed columns from metadata JSONB; migration 011 adds task_status_field_invariants CHECK.
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
#   test_migration_002_adds_node_id_on_legacy_db - migration 002 backfills node_id SERIAL PRIMARY KEY on a legacy-style DB
#   test_migration_005_converts_serial_to_identity - migration 005 converts SERIAL PKs to GENERATED ALWAYS AS IDENTITY and seeds above MAX
#   test_legacy_db_at_005_applies_006_010 - legacy DB at 005: label→title, created_at/updated_at, trigger advances updated_at, status→task_status enum, ip dropped; migration 010 extracts typed columns from metadata
#   test_fresh_db_full_shape - fresh DB: task_status enum, trigger, title/status enum/created_at/updated_at columns, typed columns (engine/extra/remote_folder/local_folder/webhook_url/error/webhook_custom_params), no ip, seeds '012'
#   test_migration_008_fails_on_out_of_range_status - migration 008 rolls back when a row has status=3 (out of enum range)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.9.0 - Extracted test_migration_012_node_rename_and_fields to test_migration_012_node_rename.py (GRACE-lite 1000-line limit compliance).
#   PREVIOUS_CHANGE: v1.8.1 - fix: update seed/tracker assertions from '011' to '012' (schema.sql last_migration bumped to '012'); renumber synthetic migration files 012→013 to avoid collision with real migration 012.
#   PREVIOUS_CHANGE: v1.8.0 - node-rename-and-fields: migration 012 renames ip→hostname, adds audit timestamps + trigger, jump fields, external_id backfill, NODE_STATUS + status, port constraints; fresh DB seeds to '012'; tracker assertions append '012'; schema.sql snapshot updated; test_migration_012_node_rename_and_fields covers all 7 Gherkin scenarios.
#   PREVIOUS_CHANGE: v1.7.0 - task-status-field-invariants: fresh DB seeds to '011' (migration 011 adds task_status_field_invariants CHECK); tracker assertions append '011'; synthetic migrations renumbered 011_*→012_* (collision with real 011); legacy/modern DBs now apply 001-011; test_legacy_db_at_005_applies_006_010 trigger UPDATE uses a real RUNNING row (allocated_node_id + remote_folder set) so the CHECK does not reject the status transition.
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
            assert seeded == ["013"]
            assert {"username", "port", "node_id"} <= set(
                _columns(conn, "yascheduler_nodes")
            )
        finally:
            conn.close()

        apply_migrations(config)

        conn = _connect(config)
        try:
            assert _tracker_rows(conn) == ["013"]
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
            conn.run(
                "CREATE TABLE yascheduler_nodes ("
                "ip VARCHAR(15) UNIQUE, cloud VARCHAR(32) DEFAULT NULL, "
                "ncpus SMALLINT DEFAULT NULL)"
            )
            # Pre-create yascheduler_tasks at the pre-004 era schema (no
            # allocated_node_id) so migration 004's ALTER ADD COLUMN is
            # valid (apply_schema's CREATE TABLE IF NOT EXISTS is a no-op
            # on the existing table; without this, schema.sql would create
            # yascheduler_tasks WITH allocated_node_id and 004 would collide).
            conn.run(
                "CREATE TABLE yascheduler_tasks ("
                "task_id SERIAL PRIMARY KEY, label VARCHAR(256), "
                "metadata JSONB, ip VARCHAR(15), status SMALLINT)"
            )
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
            assert _tracker_rows(conn) == [
                "001",
                "002",
                "003",
                "004",
                "005",
                "006",
                "007",
                "008",
                "009",
                "010",
                "011",
                "012",
                "013",
            ]
            assert {"username", "port", "node_id"} <= set(
                _columns(conn, "yascheduler_nodes")
            )
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
            conn.run(
                "CREATE TABLE yascheduler_nodes ("
                "ip VARCHAR(15) UNIQUE, cloud VARCHAR(32) DEFAULT NULL, "
                "ncpus SMALLINT DEFAULT NULL)"
            )
            conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES ('000')")
            # Pre-create yascheduler_tasks at the pre-004 era schema (no
            # allocated_node_id) so migration 004's ALTER ADD COLUMN is valid.
            conn.run(
                "CREATE TABLE yascheduler_tasks ("
                "task_id SERIAL PRIMARY KEY, label VARCHAR(256), "
                "metadata JSONB, ip VARCHAR(15), status SMALLINT)"
            )
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
            assert _tracker_rows(conn) == [
                "000",
                "001",
                "002",
                "003",
                "004",
                "005",
                "006",
                "007",
                "008",
                "009",
                "010",
                "011",
                "012",
                "013",
            ]
            assert {"username", "port", "node_id"} <= set(
                _columns(conn, "yascheduler_nodes")
            )
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
    (migrations_dir / "014_reopen.py").write_text(
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
            assert _tracker_rows(conn) == ["013", "014"]
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
    (migrations_dir / "014_fail.sql").write_text(
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
            assert "014" not in _tracker_rows(conn)
            assert not _table_exists(conn, "fail_tbl")
        finally:
            conn.close()


# START_CONTRACT: test_migration_002_adds_node_id_on_legacy_db
#   PURPOSE: Confirm migration 002 backfills node_id SERIAL PRIMARY KEY on a legacy-style DB (yascheduler_nodes present, no node_id column, no tracker).
#   INPUTS: { None - starts its own PostgresContainer }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; creates a legacy yascheduler_nodes WITHOUT node_id and inserts rows; applies schema (no-op on existing table) + migrations (002 adds node_id).
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_migration_002_adds_node_id_on_legacy_db
def test_migration_002_adds_node_id_on_legacy_db() -> None:
    """Migration 002 adds node_id SERIAL PRIMARY KEY and backfills existing rows with sequential ids."""
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)

        # Build a legacy-style DB: yascheduler_nodes WITHOUT node_id, with rows.
        conn = _connect(config)
        try:
            conn.run(
                "CREATE TABLE yascheduler_nodes ("
                "ip VARCHAR(15) UNIQUE, port INTEGER DEFAULT 22, "
                "username VARCHAR(255) DEFAULT 'root', ncpus SMALLINT DEFAULT NULL, "
                "enabled BOOLEAN DEFAULT TRUE, cloud VARCHAR(32) DEFAULT NULL)"
            )
            conn.run("INSERT INTO yascheduler_nodes (ip) VALUES ('10.0.0.1')")
            conn.run("INSERT INTO yascheduler_nodes (ip) VALUES ('10.0.0.2')")
            # Pre-create yascheduler_tasks at the pre-004 era schema (no
            # allocated_node_id) so migration 004's ALTER ADD COLUMN is valid.
            conn.run(
                "CREATE TABLE yascheduler_tasks ("
                "task_id SERIAL PRIMARY KEY, label VARCHAR(256), "
                "metadata JSONB, ip VARCHAR(15), status SMALLINT)"
            )
        finally:
            conn.close()

        # apply_schema is a no-op on the existing tables (CREATE TABLE IF NOT
        # EXISTS); apply_migrations runs 001 (adds username/port IF NOT EXISTS
        # — already present), 002 (adds node_id SERIAL PRIMARY KEY, backfilling
        # existing rows), 003 (backfill prov→'' + DROP ip UNIQUE), 004
        # (adds allocated_node_id), and 005 (converts SERIAL PKs to
        # GENERATED ALWAYS AS IDENTITY).
        apply_schema(config)
        apply_migrations(config)

        conn = _connect(config)
        try:
            # Tracker records 001-012.
            assert _tracker_rows(conn) == [
                "001",
                "002",
                "003",
                "004",
                "005",
                "006",
                "007",
                "008",
                "009",
                "010",
                "011",
                "012",
                "013",
            ]
            # node_id column now exists.
            cols = _columns(conn, "yascheduler_nodes")
            assert "node_id" in cols
            # Existing rows were backfilled with sequential positive SERIAL values
            # (physical order; PG assigns 1, 2, ... — assert they're distinct & positive).
            conn.run("BEGIN")
            try:
                rows = conn.run(
                    "SELECT node_id, hostname FROM yascheduler_nodes ORDER BY node_id"
                )
            finally:
                conn.run("ROLLBACK")
            assert len(rows) == 2
            ids = [r[0] for r in rows]
            assert all(isinstance(i, int) and i > 0 for i in ids), ids
            assert len(set(ids)) == 2, f"node_id values must be distinct, got {ids}"
        finally:
            conn.close()


# START_CONTRACT: test_migration_005_converts_serial_to_identity
#   PURPOSE: migration 005 converts SERIAL PKs to GENERATED ALWAYS AS IDENTITY on a pre-005 DB, seeding the identity sequence above MAX so the next insert does not collide.
#   INPUTS: { None - starts its own PostgresContainer }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; creates pre-005 tables with SERIAL PKs + a row; seeds tracker to '004'; applies schema + migrations (005); asserts identity columns + non-colliding inserts.
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_migration_005_converts_serial_to_identity
def test_migration_005_converts_serial_to_identity() -> None:
    """Migration 005 converts SERIAL PRIMARY KEY to GENERATED ALWAYS AS IDENTITY."""
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)

        # Build a pre-005 DB: both PKs are SERIAL, with one node row inserted so
        # the SERIAL sequence is at 1 (node_id=1). Seed the tracker to '004' so
        # apply_migrations runs only 005.
        conn = _connect(config)
        try:
            conn.run(
                "CREATE TABLE yascheduler_nodes ("
                "node_id SERIAL PRIMARY KEY, ip VARCHAR(15), port INTEGER DEFAULT 22, "
                "username VARCHAR(255) DEFAULT 'root', ncpus SMALLINT DEFAULT NULL, "
                "enabled BOOLEAN DEFAULT TRUE, cloud VARCHAR(32) DEFAULT NULL)"
            )
            conn.run(
                "CREATE TABLE yascheduler_tasks ("
                "task_id SERIAL PRIMARY KEY, label VARCHAR(256), metadata JSONB, "
                "ip VARCHAR(15), status SMALLINT, "
                "allocated_node_id INTEGER)"
            )
            conn.run("INSERT INTO yascheduler_nodes (ip) VALUES ('10.0.0.1')")
            # Note the SERIAL-assigned id (expected: 1).
            conn.run("BEGIN")
            try:
                assigned = conn.run(
                    "SELECT node_id FROM yascheduler_nodes WHERE ip = '10.0.0.1'"
                )
            finally:
                conn.run("ROLLBACK")
            pre_node_id = assigned[0][0]
            assert pre_node_id == 1, pre_node_id
            conn.run(
                "CREATE TABLE yascheduler_migrations "
                "(migration_id TEXT PRIMARY KEY, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES ('004')")
        finally:
            conn.close()

        # apply_schema's DO block is a no-op (tracker exists); the CREATE TABLE
        # IF NOT EXISTS is a no-op on the existing tables. apply_migrations runs
        # only 005 (prefix_id '005' > '004').
        apply_schema(config)
        apply_migrations(config)

        conn = _connect(config)
        try:
            # (a) Both PK columns are now GENERATED ALWAYS AS IDENTITY.
            conn.run("BEGIN")
            try:
                rows = conn.run(
                    "SELECT table_name, column_name, is_identity, "
                    "identity_generation FROM information_schema.columns "
                    "WHERE (table_name, column_name) IN "
                    "(('yascheduler_nodes','node_id'),"
                    "('yascheduler_tasks','task_id')) "
                    "ORDER BY table_name"
                )
            finally:
                conn.run("ROLLBACK")
            assert len(rows) == 2, rows
            for _tbl, _col, is_identity, gen in rows:
                assert is_identity == "YES", (_tbl, _col, is_identity)
                assert gen == "ALWAYS", (_tbl, _col, gen)

            # The tracker now records 004 (seeded) and 005-013 (applied).
            assert _tracker_rows(conn) == [
                "004",
                "005",
                "006",
                "007",
                "008",
                "009",
                "010",
                "011",
                "012",
                "013",
            ]

            # (b) The identity sequence next value > the previously inserted id,
            # so the next insert will not collide. The identity sequence was
            # seeded via setval(..., MAX+1, false) so nextval returns MAX+1
            # (pre_node_id=1, MAX=1 → nextval returns 2). nextval consumes the
            # value; assertion (c) below then gets the following value (3).
            conn.run("BEGIN")
            try:
                next_id = conn.run(
                    "SELECT nextval(pg_get_serial_sequence('yascheduler_nodes',"
                    "'node_id'))"
                )
            finally:
                conn.run("ROLLBACK")
            assert next_id[0][0] > pre_node_id, (next_id[0][0], pre_node_id)

            # (c) A subsequent insert auto-assigns a unique id (no collision).
            conn.run("BEGIN")
            try:
                inserted = conn.run(
                    "INSERT INTO yascheduler_nodes (hostname) VALUES ('10.0.0.2') "
                    "RETURNING node_id"
                )
                node_rows = conn.run(
                    "SELECT node_id FROM yascheduler_nodes ORDER BY node_id"
                )
            finally:
                conn.run("ROLLBACK")
            new_id = inserted[0][0]
            assert new_id > pre_node_id, (new_id, pre_node_id)
            assert {r[0] for r in node_rows} == {pre_node_id, new_id}, node_rows
        finally:
            conn.close()


# START_CONTRACT: test_legacy_db_at_005_applies_006_010
#   PURPOSE: On a legacy DB at migration 005, apply_migrations runs 006-010; assert label→title rename, created_at/updated_at, trigger, status enum, ip dropped; migration 010 extracts typed columns from metadata.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; legacy seed at 005; applies migrations
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_legacy_db_at_005_applies_006_010
def test_legacy_db_at_005_applies_006_010() -> None:
    """Legacy DB at migration 005: migrations 006-010 produce the final schema shape."""
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)

        # Build a legacy DB at migration 005: pre-006 schema (label, status SMALLINT, ip, no created_at/updated_at).
        conn = _connect(config)
        try:
            conn.run(
                "CREATE TABLE yascheduler_migrations "
                "(migration_id TEXT PRIMARY KEY, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES ('005')")
            conn.run(
                "CREATE TABLE yascheduler_nodes ("
                "node_id SERIAL PRIMARY KEY, ip VARCHAR(15), "
                "port INTEGER DEFAULT 22, username VARCHAR(255) DEFAULT 'root', "
                "ncpus SMALLINT DEFAULT NULL, enabled BOOLEAN DEFAULT TRUE, "
                "cloud VARCHAR(32) DEFAULT NULL)"
            )
            # Pre-006 schema: label (not title), status SMALLINT, ip present.
            # allocated_node_id IS present (added by migration 004, which a DB
            # at 005 has already applied) — required so migration 011's CHECK
            # referencing allocated_node_id can compile.
            conn.run(
                "CREATE TABLE yascheduler_tasks ("
                "task_id SERIAL PRIMARY KEY, label VARCHAR(256), "
                "metadata JSONB, ip VARCHAR(15), status SMALLINT, "
                "allocated_node_id INTEGER)"
            )
            conn.run(
                "INSERT INTO yascheduler_tasks (label, ip, status, metadata) "
                "VALUES ('legacy_task', '10.0.0.1', 0, '{}'::jsonb)"
            )
        finally:
            conn.close()

        apply_schema(config)
        apply_migrations(config)

        conn = _connect(config)
        try:
            cols = _columns(conn, "yascheduler_tasks")
            # label was renamed to title
            assert "label" not in cols
            assert "title" in cols
            # ip column was dropped
            assert "ip" not in cols
            # created_at and updated_at present
            assert "created_at" in cols
            assert "updated_at" in cols
            # Migration 010: metadata dropped, typed columns extracted
            assert "metadata" not in cols
            assert "engine" in cols
            assert "extra" in cols
            assert "remote_folder" in cols
            assert "local_folder" in cols
            assert "webhook_url" in cols
            assert "error" in cols
            assert "webhook_custom_params" in cols

            # status column type is task_status enum with correct labels
            conn.run("BEGIN")
            try:
                type_rows = conn.run(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'yascheduler_tasks' AND column_name = 'status'"
                )
            finally:
                conn.run("ROLLBACK")
            assert type_rows[0][0] == "USER-DEFINED"

            conn.run("BEGIN")
            try:
                enum_rows = conn.run(
                    "SELECT e.enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'task_status' ORDER BY e.enumsortorder"
                )
            finally:
                conn.run("ROLLBACK")
            assert [r[0] for r in enum_rows] == ["TO_DO", "RUNNING", "DONE"]

            # Trigger exists
            conn.run("BEGIN")
            try:
                trig_rows = conn.run(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid = 'yascheduler_tasks'::regclass "
                    "AND tgname = 'yascheduler_tasks_touch_updated_at'"
                )
            finally:
                conn.run("ROLLBACK")
            assert len(trig_rows) == 1

            # Insert a row, commit, then UPDATE in a new transaction so the
            # trigger's NOW() (transaction-start time) differs from the INSERT's NOW().
            conn.run("BEGIN")
            try:
                conn.run(
                    "INSERT INTO yascheduler_tasks (title, status, engine) "
                    "VALUES ('trigger_test', 'TO_DO', 'fleur')"
                )
            finally:
                conn.run("COMMIT")

            conn.run("BEGIN")
            try:
                row = conn.run(
                    "SELECT task_id, created_at, updated_at "
                    "FROM yascheduler_tasks WHERE title = 'trigger_test'"
                )
                assert len(row) == 1
                task_id = row[0][0]
                created_before = row[0][1]
                updated_before = row[0][2]

                # Sleep a tiny bit so the timestamps differ.
                import time as _time

                _time.sleep(0.05)

                # Transition TO_DO → DONE (DONE is unconstrained by the
                # task_status_field_invariants CHECK, so this UPDATE succeeds
                # where TO_DO → RUNNING would be rejected: RUNNING requires
                # allocated_node_id + remote_folder, which this row lacks).
                conn.run(
                    "UPDATE yascheduler_tasks SET status = 'DONE' WHERE task_id = :tid",
                    tid=task_id,
                )
                row2 = conn.run(
                    "SELECT created_at, updated_at "
                    "FROM yascheduler_tasks WHERE task_id = :tid",
                    tid=task_id,
                )
                assert row2[0][0] == created_before, (
                    "created_at must NOT change on UPDATE"
                )
                assert row2[0][1] > updated_before, "updated_at must advance on UPDATE"
            finally:
                conn.run("ROLLBACK")

            # Tracker records 005 (seeded) + 006, 007, 008, 009, 010, 011, 012, 013
            assert _tracker_rows(conn) == [
                "005",
                "006",
                "007",
                "008",
                "009",
                "010",
                "011",
                "012",
                "013",
            ]

            # The legacy row's status was converted via the USING clause.
            conn.run("BEGIN")
            try:
                legacy = conn.run(
                    "SELECT title, status::text FROM yascheduler_tasks "
                    "WHERE title = 'legacy_task'"
                )
            finally:
                conn.run("ROLLBACK")
            assert legacy[0][1] == "TO_DO"
        finally:
            conn.close()


# START_CONTRACT: test_fresh_db_full_shape
#   PURPOSE: On a fresh DB, apply_schema creates the final schema shape; apply_migrations is a no-op.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; applies schema + migrations
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: test_fresh_db_full_shape
def test_fresh_db_full_shape() -> None:
    """Fresh DB: apply_schema produces final shape; apply_migrations is no-op."""
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)
        apply_schema(config)

        conn = _connect(config)
        try:
            # Tracker seeds to '013'
            assert _tracker_rows(conn) == ["013"]

            cols = _columns(conn, "yascheduler_tasks")
            assert "task_id" in cols
            assert "title" in cols  # not label
            assert "status" in cols
            assert "metadata" not in cols  # dropped by migration 010
            assert "engine" in cols
            assert "remote_folder" in cols
            assert "local_folder" in cols
            assert "webhook_url" in cols
            assert "error" in cols
            assert "webhook_custom_params" in cols
            assert "extra" in cols
            assert "allocated_node_id" in cols
            assert "created_at" in cols
            assert "updated_at" in cols
            assert "ip" not in cols  # dropped

            # status column type is task_status enum
            conn.run("BEGIN")
            try:
                type_rows = conn.run(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'yascheduler_tasks' AND column_name = 'status'"
                )
            finally:
                conn.run("ROLLBACK")
            assert type_rows[0][0] == "USER-DEFINED"

            # Trigger exists
            conn.run("BEGIN")
            try:
                trig_rows = conn.run(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid = 'yascheduler_tasks'::regclass "
                    "AND tgname = 'yascheduler_tasks_touch_updated_at'"
                )
            finally:
                conn.run("ROLLBACK")
            assert len(trig_rows) == 1
        finally:
            conn.close()

        # apply_migrations finds MAX='013' and applies nothing.
        apply_migrations(config)

        conn = _connect(config)
        try:
            assert _tracker_rows(conn) == ["013"]
        finally:
            conn.close()


# START_CONTRACT: test_migration_008_fails_on_out_of_range_status
#   PURPOSE: On a legacy DB at 007 with a row status=3, migration 008 fails (USING CASE maps 3→NULL, NOT NULL violates), rolls back.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based }
#   SIDE_EFFECTS: Starts a Postgres container; seeds legacy DB with bad row; applies migrations; asserts rollback.
#   LINKS: M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-SCHEMA
# END_CONTRACT: test_migration_008_fails_on_out_of_range_status
def test_migration_008_fails_on_out_of_range_status() -> None:
    """Migration 008 fails (rolls back) when a row has out-of-range status (e.g. 3)."""
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)

        conn = _connect(config)
        try:
            conn.run(
                "CREATE TABLE yascheduler_migrations "
                "(migration_id TEXT PRIMARY KEY, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES ('007')")
            conn.run(
                "CREATE TABLE yascheduler_nodes ("
                "node_id SERIAL PRIMARY KEY, ip VARCHAR(15), "
                "port INTEGER DEFAULT 22, username VARCHAR(255) DEFAULT 'root', "
                "ncpus SMALLINT DEFAULT NULL, enabled BOOLEAN DEFAULT TRUE, "
                "cloud VARCHAR(32) DEFAULT NULL)"
            )
            # Pre-008 schema: status SMALLINT NOT NULL DEFAULT 0, no allocated_node_id, no type.
            conn.run(
                "CREATE TABLE yascheduler_tasks ("
                "task_id SERIAL PRIMARY KEY, label VARCHAR(256), "
                "metadata JSONB, ip VARCHAR(15), "
                "status SMALLINT NOT NULL DEFAULT 0)"
            )
            # Row with out-of-range status = 3 (maps to NULL via USING CASE).
            conn.run(
                "INSERT INTO yascheduler_tasks (label, status, metadata) "
                "VALUES ('bad', 3, '{}'::jsonb)"
            )
        finally:
            conn.close()

        # apply_schema is a no-op on existing tables.
        apply_schema(config)

        # apply_migrations runs 008; it should fail because status=3 → NULL violates NOT NULL.
        with pytest.raises(DatabaseError):
            apply_migrations(config)

        conn = _connect(config)
        try:
            # Migration 008 NOT recorded in tracker.
            assert _tracker_rows(conn) == ["007"]
            # status column remains SMALLINT (rollback restored the schema).
            conn.run("BEGIN")
            try:
                type_rows = conn.run(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'yascheduler_tasks' AND column_name = 'status'"
                )
            finally:
                conn.run("ROLLBACK")
            assert type_rows[0][0] == "smallint"
        finally:
            conn.close()
