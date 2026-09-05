# region MODULE_CONTRACT
# PURPOSE: Integration regression test for migration 004 backfill (allocated_node_id).
# SCOPE: guards the ip='' multi-row crash (post-003 prov* nodes) and the
#        TO_DO / migration-011 CHECK conflict; verifies the WHERE ip <> '' +
#        LIMIT 1 fix.
# KEYWORDS: migration 004, allocated_node_id, backfill, prov node, empty ip
# endregion MODULE_CONTRACT

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pg8000.native
import pytest
from testcontainers.postgres import PostgresContainer

from yascheduler.infra.persistence import PostgresDbConfig

pytestmark = pytest.mark.integration

_MIGRATION_004 = (
    Path(__file__).resolve().parents[2]
    / "yascheduler"
    / "infra"
    / "persistence"
    / "sql"
    / "migrations"
    / "004_add_allocated_node_id.sql"
)


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


def _seed_post_003(conn: pg8000.native.Connection) -> None:
    """Build a legacy DB as it looks right after migration 003 applied."""
    conn.run(
        "CREATE TABLE yascheduler_migrations "
        "(migration_id TEXT PRIMARY KEY, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    )
    conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES ('003')")
    # Post-002 nodes: node_id PK + ip. After 003 former prov* nodes share ip=''.
    conn.run(
        "CREATE TABLE yascheduler_nodes ("
        "node_id SERIAL PRIMARY KEY, ip VARCHAR(15), "
        "port INTEGER DEFAULT 22, username VARCHAR(255) DEFAULT 'root', "
        "ncpus SMALLINT DEFAULT NULL, enabled BOOLEAN DEFAULT TRUE, "
        "cloud VARCHAR(32) DEFAULT NULL)"
    )
    # Pre-004 tasks: ip present, no allocated_node_id yet.
    conn.run(
        "CREATE TABLE yascheduler_tasks ("
        "task_id SERIAL PRIMARY KEY, label VARCHAR(256), "
        "metadata JSONB, ip VARCHAR(15), status SMALLINT)"
    )


def test_migration_004_backfill_handles_empty_and_duplicate_ips() -> None:
    """ip='' (post-003 prov* nodes + TO_DO sentinel) must not crash the scalar
    subquery and must stay NULL so the migration 011 CHECK later passes;
    genuine duplicate real IPs resolve via LIMIT 1."""
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        config = _make_config(pg)

        conn = _connect(config)
        try:
            _seed_post_003(conn)
            # Two former prov* nodes now sharing ip='' (the 003 outcome).
            conn.run("INSERT INTO yascheduler_nodes (ip) VALUES ('')")
            conn.run("INSERT INTO yascheduler_nodes (ip) VALUES ('')")
            # Unique real-ip node (node_id 3).
            conn.run("INSERT INTO yascheduler_nodes (ip) VALUES ('10.0.0.1')")
            # Two nodes colliding on a real ip (genuine duplicate, node_ids 4,5).
            conn.run("INSERT INTO yascheduler_nodes (ip) VALUES ('10.0.0.9')")
            conn.run("INSERT INTO yascheduler_nodes (ip) VALUES ('10.0.0.9')")

            # ip='' task: the legacy TO_DO unallocated sentinel. Pre-fix this
            # raised "more than one row returned by a subquery used as an
            # expression" and would also break the 011 CHECK.
            conn.run(
                "INSERT INTO yascheduler_tasks (label, ip, status, metadata) "
                "VALUES ('todo_empty', '', 0, '{}'::jsonb)"
            )
            conn.run(
                "INSERT INTO yascheduler_tasks (label, ip, status, metadata) "
                "VALUES ('real_unique', '10.0.0.1', 1, '{}'::jsonb)"
            )
            conn.run(
                "INSERT INTO yascheduler_tasks (label, ip, status, metadata) "
                "VALUES ('real_dup', '10.0.0.9', 1, '{}'::jsonb)"
            )
        finally:
            conn.close()

        # Apply migration 004 exactly as the runner does: whole file text in one
        # transaction.
        conn = _connect(config)
        try:
            conn.run("BEGIN")
            try:
                conn.run(_MIGRATION_004.read_text())
                conn.run("COMMIT")
            except Exception:
                conn.run("ROLLBACK")
                raise
        finally:
            conn.close()

        conn = _connect(config)
        try:
            conn.run("BEGIN")
            try:
                rows = conn.run(
                    "SELECT label, allocated_node_id FROM yascheduler_tasks "
                    "ORDER BY task_id"
                )
            finally:
                conn.run("ROLLBACK")
            by_label = dict(rows)

            # ip='' untouched (no crash, stays NULL -> satisfies 011 CHECK).
            assert by_label["todo_empty"] is None
            # Unique real ip backfilled to the matching node (node_id 3).
            assert by_label["real_unique"] == 3
            # Duplicate real ip resolved by ORDER BY node_id LIMIT 1 to the
            # earliest inserted matching node (node_id 4).
            assert by_label["real_dup"] == 4
        finally:
            conn.close()
