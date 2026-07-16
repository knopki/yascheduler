"""Apply pending database schema/data migrations in forward-only order."""
# region MODULE_CONTRACT
# PURPOSE: Evolve the database schema and data forward in production — one migration per tracker-recorded transaction — so the team makes incremental, replayable changes without manual DDL scripting.
# SCOPE: Forward-only DDL/DML migration application over sql/migrations/ via one pg8000 connection, one transaction per migration, with yascheduler_migrations tracker recording.
# DEPENDENCIES: USES API: pg8000.Connection, READS: migration files (.sql, .py) from sql/migrations/, LOADS: Python migration modules dynamically via importlib
# KEYWORDS: migration, apply, database, dml, ddl
# endregion MODULE_CONTRACT

from __future__ import annotations

import contextlib
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pg8000 import DatabaseError
from pg8000.native import Connection

from .migration_base import Migration

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from types import ModuleType

    from .db_config import PostgresDbConfig

__all__ = ["apply_migrations"]

_MIGRATIONS_DIR = Path(__file__).parent / "sql" / "migrations"


def _prefix_id(filename: Path) -> str:
    return filename.name.split("_", 1)[0]


# region FUNC__scan_migrations
# PURPOSE: Discover all available migration files so the runner can determine which ones need applying, in filename order.
def _scan_migrations() -> list[Path]:
    files = list(_MIGRATIONS_DIR.glob("*.sql")) + list(_MIGRATIONS_DIR.glob("*.py"))
    return sorted(files, key=lambda f: f.name)


# endregion FUNC__scan_migrations


# region FUNC__last_applied
# PURPOSE: Determine the last successfully applied migration so the runner applies only newer files and avoids re-executing already-recorded steps.
# ENSURES: Returns None when the tracker table is empty or absent (defensive — apply_schema is contractually run first).
def _last_applied(conn: Connection) -> str | None:
    try:
        rows = conn.run("SELECT MAX(migration_id) FROM yascheduler_migrations")
    except DatabaseError:
        # Defensive: apply_schema is contractually run first and creates the
        # tracker. Treat its absence as "apply all" rather than crashing.
        return None
    if not rows or rows[0][0] is None:
        return None
    return str(rows[0][0])


# endregion FUNC__last_applied


# region FUNC__pending
# PURPOSE: Compute the set of not-yet-applied migrations so the runner applies only what is needed, preserving chronological order.
def _pending(last: str | None, files: list[Path]) -> list[Path]:
    if last is None:
        return list(files)
    return [f for f in files if _prefix_id(f) > last]


# endregion FUNC__pending


# region FUNC__one_migration_subclass
# PURPOSE: Extract the single Migration subclass from a .py migration file so the runner can call migrate() — fails loud on ambiguous or empty files to prevent silent skips.
def _one_migration_subclass(module: ModuleType) -> type[Migration]:
    candidates = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, Migration)
        and cls is not Migration
        and cls.__module__ == module.__name__
    ]
    if len(candidates) != 1:
        msg = (
            f"{module.__file__}: expected exactly one Migration subclass, "
            f"found {len(candidates)}"
        )
        raise RuntimeError(msg)
    return candidates[0]


# endregion FUNC__one_migration_subclass


def _rollback(conn: Connection) -> None:
    # region BLOCK_rollback
    with contextlib.suppress(Exception):
        conn.run("ROLLBACK")
    # endregion BLOCK_rollback


# region FUNC__apply_sql_migration
# PURPOSE: Execute a .sql migration file atomically and record it in the tracker so the schema evolves safely and re-runs are prevented.
def _apply_sql_migration(conn: Connection, path: Path, prefix_id: str) -> None:
    conn.run("BEGIN")
    try:
        # region BLOCK_apply_sql
        conn.run(path.read_text())
        conn.run(
            "INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)",
            p=prefix_id,
        )
        conn.run("COMMIT")
        logger.debug("APPLY_SQL", extra={"prefix": prefix_id})
        # endregion BLOCK_apply_sql
    except Exception:
        _rollback(conn)
        raise


# endregion FUNC__apply_sql_migration


# region FUNC__record_py_tracker
# PURPOSE: Persist the tracker record for a .py migration after migrate() succeeds so the same step is never re-applied, even if the runner crashes after the SQL landed.
def _record_py_tracker(conn: Connection, prefix_id: str) -> None:
    # region BLOCK_tracker_record
    # pg8000 native AUTOCOMMITS statements issued outside an open
    # transaction, and a bare COMMIT with no open transaction is a no-op
    # warning rather than an error. Consequently, when migrate() closed the
    # runner's transaction via self.commit() (for a non-transactional op like
    # CREATE INDEX CONCURRENTLY), the INSERT below simply autocommits and
    # COMMIT is a no-op — the tracker is recorded in both the normal and the
    # commit-closed cases (migrate() applied <=> tracker recorded).
    #
    # The except-DatabaseError reopen branch is a defensive guard for
    # transient DB-side errors on the tracker INSERT/COMMIT (e.g. a deadlock):
    # it reopens a fresh transaction and retries the record once. A real
    # failure (e.g. a duplicate-prefix_id PK violation) is re-raised by the
    # retry and handled by the caller's ROLLBACK.
    try:
        conn.run(
            "INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)",
            p=prefix_id,
        )
        conn.run("COMMIT")
    except DatabaseError as exc:
        logger.debug("TRACKER_RECORD", extra={"exc": exc})
        conn.run("BEGIN")
        conn.run(
            "INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)",
            p=prefix_id,
        )
        conn.run("COMMIT")
    logger.debug("TRACKER_RECORD", extra={"prefix": prefix_id})
    # endregion BLOCK_tracker_record


# endregion FUNC__record_py_tracker


# region FUNC__apply_py_migration
# PURPOSE: Execute a Python migration step inside a transaction — load the module, call migrate(), and record the tracker — so complex DDL/DML logic runs safely and is never re-applied.
def _apply_py_migration(
    conn: Connection,
    path: Path,
    prefix_id: str,
    config: PostgresDbConfig,
) -> None:
    spec = importlib.util.spec_from_file_location(prefix_id, path)
    if spec is None or spec.loader is None:
        msg = f"{path}: cannot load migration module"
        raise RuntimeError(msg)
    conn.run("BEGIN")
    try:
        # region BLOCK_apply_py
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        klass = _one_migration_subclass(module)
        migration = klass(config, conn, logger)
        migration.migrate()
        # endregion BLOCK_apply_py

        _record_py_tracker(conn, prefix_id)
    except Exception:
        _rollback(conn)
        raise


# endregion FUNC__apply_py_migration


# region FUNC_apply_migrations
# PURPOSE: Apply all pending schema/data migrations in forward order so the database is up-to-date on every deployment without manual SQL intervention.
def apply_migrations(config: PostgresDbConfig) -> None:
    """Apply pending migrations from sql/migrations/ to the DB described by config, each in its own transaction."""
    conn: Connection | None = None
    try:
        # region BLOCK_open_connection
        conn = Connection(
            user=config.user,
            host=config.host,
            database=config.database,
            port=config.port,
            password=config.password,
        )
        # endregion BLOCK_open_connection

        # region BLOCK_read_last
        last = _last_applied(conn)
        files = _scan_migrations()
        pending = _pending(last, files)
        logger.debug("READ_LAST", extra={"last": last, "pending": len(pending)})
        # endregion BLOCK_read_last

        # region BLOCK_apply_pending
        for path in pending:
            pid = _prefix_id(path)
            if path.suffix == ".sql":
                _apply_sql_migration(conn, path, pid)
            else:
                _apply_py_migration(conn, path, pid, config)
            logger.debug("APPLY_PENDING", extra={"prefix": pid})
        # endregion BLOCK_apply_pending
    finally:
        # region BLOCK_close
        if conn is not None:
            conn.close()
        # endregion BLOCK_close


# endregion FUNC_apply_migrations
