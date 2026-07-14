# FILE: yascheduler/infra/persistence/postgres_migrations.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Apply pending database schema/data migrations in forward-only order.
#   SCOPE: Forward-only DDL/DML migration application over sql/migrations/ via one pg8000 connection, one transaction per migration, with yascheduler_migrations tracker recording.
#   DEPENDS: M-INFRA-DB-CONFIG, M-PERSISTENCE-MIGRATION-BASE
#   LINKS: M-PERSISTENCE, M-PERSISTENCE-SCHEMA, M-ENTRYPOINTS-CLI-INIT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   apply_migrations - apply pending migrations from sql/migrations/ to the DB behind config
#   _prefix_id - prefix token of a migration filename
#   _scan_migrations - sorted list of *.sql + *.py files under _MIGRATIONS_DIR
#   _last_applied - MAX(migration_id) from yascheduler_migrations, or None
#   _pending - filter scanned files to prefix_id > last
#   _one_migration_subclass - the single Migration subclass defined in a .py module
#   _apply_sql_migration - apply a .sql migration in one transaction
#   _apply_py_migration - apply a .py migration (Migration subclass) in one transaction
#   _record_py_tracker - record a .py migration in the tracker (reopen txn on transient error)
#   _rollback - best-effort ROLLBACK wrapper
#   _MIGRATIONS_DIR - path to the bundled sql/migrations/ directory
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - remove log parameter from function signatures; bind module-local logger = get_logger("M-PERSISTENCE-MIGRATIONS") at module top
#   PREVIOUS_CHANGE: v1.0.0 - Introduce forward-only migration runner. Applies .sql (multi-statement) and .py (Migration subclass) migrations in string-sorted prefix_id order, one transaction per migration.
# END_CHANGE_SUMMARY

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

from pg8000 import DatabaseError
from pg8000.native import Connection

from yascheduler.shared import get_logger

from .migration_base import Migration

logger = get_logger("M-PERSISTENCE-MIGRATIONS")

if TYPE_CHECKING:
    from types import ModuleType

    from .db_config import PostgresDbConfig

_MIGRATIONS_DIR = Path(__file__).parent / "sql" / "migrations"


def _prefix_id(filename: Path) -> str:
    return filename.name.split("_", 1)[0]


# START_CONTRACT: _scan_migrations
#   PURPOSE: List all .sql and .py migration files under _MIGRATIONS_DIR, sorted by filename (string sort).
#   INPUTS: { None }
#   OUTPUTS: { list[Path] - sorted migration file paths }
#   SIDE_EFFECTS: Reads the _MIGRATIONS_DIR directory.
#   LINKS: _prefix_id, apply_migrations
# END_CONTRACT: _scan_migrations
def _scan_migrations() -> list[Path]:
    files = list(_MIGRATIONS_DIR.glob("*.sql")) + list(_MIGRATIONS_DIR.glob("*.py"))
    return sorted(files, key=lambda f: f.name)


# START_CONTRACT: _last_applied
#   PURPOSE: Read the highest recorded migration_id from yascheduler_migrations; None means "apply all".
#   INPUTS: { conn: Connection - open pg8000 native connection }
#   OUTPUTS: { str | None - MAX(migration_id), or None when the tracker is empty or (defensively) absent }
#   SIDE_EFFECTS: Reads the yascheduler_migrations table.
#   LINKS: apply_migrations, M-PERSISTENCE-SCHEMA (tracker created by the schema DO block)
# END_CONTRACT: _last_applied
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


# START_CONTRACT: _pending
#   PURPOSE: Filter scanned migration files to those whose prefix_id is greater than last, preserving sorted order.
#   INPUTS: { last: str | None - last applied prefix_id (None → all files pending), files: list[Path] - scanned files (assumed sorted by filename) }
#   OUTPUTS: { list[Path] - pending files in the input order }
#   SIDE_EFFECTS: None
#   LINKS: _prefix_id, apply_migrations
# END_CONTRACT: _pending
def _pending(last: str | None, files: list[Path]) -> list[Path]:
    if last is None:
        return list(files)
    return [f for f in files if _prefix_id(f) > last]


# START_CONTRACT: _one_migration_subclass
#   PURPOSE: Discover exactly one Migration subclass defined in the given module; fail loudly on 0 or >1.
#   INPUTS: { module: ModuleType - a freshly loaded .py migration module }
#   OUTPUTS: { type[Migration] - the single Migration subclass defined in the module }
#   SIDE_EFFECTS: None
#   RAISES: { RuntimeError - when the count of Migration subclasses defined in the module is not exactly 1 }
#   LINKS: _apply_py_migration, M-PERSISTENCE-MIGRATION-BASE
# END_CONTRACT: _one_migration_subclass
def _one_migration_subclass(module: ModuleType) -> type[Migration]:
    candidates = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, Migration)
        and cls is not Migration
        and cls.__module__ == module.__name__
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"{module.__file__}: expected exactly one Migration subclass, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def _rollback(conn: Connection) -> None:
    # START_BLOCK_ROLLBACK
    try:
        conn.run("ROLLBACK")
    except Exception:
        pass
    # END_BLOCK_ROLLBACK


# START_CONTRACT: _apply_sql_migration
#   PURPOSE: Apply a .sql migration in one transaction: BEGIN → run full SQL text (multi-statement) → INSERT tracker → COMMIT; ROLLBACK and re-raise on any error.
#   INPUTS: { conn: Connection - open pg8000 native connection, path: Path - .sql migration file, prefix_id: str - the migration's prefix_id }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Runs the migration's DDL/DML; inserts a row into yascheduler_migrations; opens/closes one transaction
#   LINKS: apply_migrations
# END_CONTRACT: _apply_sql_migration
def _apply_sql_migration(conn: Connection, path: Path, prefix_id: str) -> None:
    conn.run("BEGIN")
    try:
        # START_BLOCK_APPLY_SQL
        conn.run(path.read_text())
        conn.run(
            "INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)",
            p=prefix_id,
        )
        conn.run("COMMIT")
        logger.trace("APPLY_SQL", prefix=prefix_id)
        # END_BLOCK_APPLY_SQL
    except Exception:
        _rollback(conn)
        raise


# START_CONTRACT: _record_py_tracker
#   PURPOSE: Record a .py migration in yascheduler_migrations after migrate() returns, honoring the best-effort atomic contract.
#   INPUTS: { conn: Connection - open pg8000 native connection (transaction may or may not be open), prefix_id: str - the migration's prefix_id }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: INSERTs a tracker row and COMMITs; may reopen a fresh transaction on a transient DatabaseError
#   LINKS: _apply_py_migration
# END_CONTRACT: _record_py_tracker
def _record_py_tracker(conn: Connection, prefix_id: str) -> None:
    # START_BLOCK_TRACKER_RECORD
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
        logger.trace(
            "TRACKER_RECORD",
            exc=exc,
        )
        conn.run("BEGIN")
        conn.run(
            "INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)",
            p=prefix_id,
        )
        conn.run("COMMIT")
    logger.trace("TRACKER_RECORD", prefix=prefix_id)
    # END_BLOCK_TRACKER_RECORD


# START_CONTRACT: _apply_py_migration
#   PURPOSE: Apply a .py migration in one transaction: BEGIN → load module → instantiate the single Migration subclass → migrate() → best-effort tracker record; ROLLBACK and re-raise on any error.
#   INPUTS: { conn: Connection - open pg8000 native connection, path: Path - .py migration file, prefix_id: str - the migration's prefix_id (also used as the module name), config: PostgresDbConfig }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Loads and executes a .py module; the migration runs DDL/DML via the injected conn; inserts a row into yascheduler_migrations
#   LINKS: _one_migration_subclass, _record_py_tracker, apply_migrations, M-PERSISTENCE-MIGRATION-BASE
# END_CONTRACT: _apply_py_migration
def _apply_py_migration(
    conn: Connection,
    path: Path,
    prefix_id: str,
    config: PostgresDbConfig,
) -> None:
    conn.run("BEGIN")
    try:
        # START_BLOCK_APPLY_PY
        spec = importlib.util.spec_from_file_location(prefix_id, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"{path}: cannot load migration module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        klass = _one_migration_subclass(module)
        migration = klass(config, conn, logger)
        migration.migrate()
        # END_BLOCK_APPLY_PY

        _record_py_tracker(conn, prefix_id)
    except Exception:
        _rollback(conn)
        raise


# START_CONTRACT: apply_migrations
#   PURPOSE: Apply pending migrations from sql/migrations/ to the DB described by config, each in its own transaction.
#   INPUTS: { config: PostgresDbConfig - database connection parameters }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Runs DDL/DML per pending migration; writes to yascheduler_migrations; opens/closes one pg8000 connection (and one transaction per pending migration)
#   LINKS: M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-SCHEMA
# END_CONTRACT: apply_migrations
def apply_migrations(config: PostgresDbConfig) -> None:
    conn: Connection | None = None
    try:
        # START_BLOCK_OPEN_CONNECTION
        conn = Connection(
            user=config.user,
            host=config.host,
            database=config.database,
            port=config.port,
            password=config.password,
        )
        logger.trace("OPEN_CONNECTION")
        # END_BLOCK_OPEN_CONNECTION

        # START_BLOCK_READ_LAST
        last = _last_applied(conn)
        files = _scan_migrations()
        pending = _pending(last, files)
        logger.trace("READ_LAST", last=last, pending=len(pending))
        # END_BLOCK_READ_LAST

        # START_BLOCK_APPLY_PENDING
        for path in pending:
            pid = _prefix_id(path)
            if path.suffix == ".sql":
                _apply_sql_migration(conn, path, pid)
            else:
                _apply_py_migration(conn, path, pid, config)
            logger.trace("APPLY_PENDING", prefix=pid)
        # END_BLOCK_APPLY_PENDING
    finally:
        # START_BLOCK_CLOSE
        if conn is not None:
            conn.close()
            logger.trace("CLOSE")
        # END_BLOCK_CLOSE
