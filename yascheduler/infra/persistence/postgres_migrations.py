# FILE: yascheduler/infra/persistence/postgres_migrations.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Synchronous migration runner — scans sql/migrations/, applies pending .sql/.py migrations in string-sorted prefix_id order, each in its own transaction, recording each in yascheduler_migrations.
#   SCOPE: apply_migrations(config); private helpers for prefix parsing, scanning, pending filter, .py class discovery, sql/py application, rollback.
#   DEPENDS: M-INFRA-DB-CONFIG, M-PERSISTENCE-MIGRATION-BASE
#   LINKS: M-PERSISTENCE, M-PERSISTENCE-SCHEMA, M-ENTRYPOINTS-CLI-INIT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   apply_migrations - apply pending migrations from sql/migrations/ to the DB behind config
#   _prefix_id - token before the first '_' in a migration filename
#   _scan_migrations - glob *.sql + *.py under _MIGRATIONS_DIR, sorted by filename
#   _last_applied - SELECT MAX(migration_id) from yascheduler_migrations (None if empty/absent)
#   _pending - filter scanned files to those with prefix_id > last (or all when last is None)
#   _one_migration_subclass - discover exactly one Migration subclass in a .py migration module
#   _apply_sql_migration - BEGIN → run sql text → INSERT tracker → COMMIT (rollback on error)
#   _apply_py_migration - BEGIN → load module → migrate() → best-effort tracker record (rollback on error)
#   _record_py_tracker - record a .py migration in the tracker; reopen txn on transient DatabaseError
#   _rollback - best-effort ROLLBACK wrapper
#   _MIGRATIONS_DIR - path to the bundled sql/migrations/ directory
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Introduce forward-only migration runner (add-db-migrations). Applies .sql (multi-statement) and .py (Migration subclass) migrations in string-sorted prefix_id order, each in its own transaction, recording each in yascheduler_migrations.
# END_CHANGE_SUMMARY

from __future__ import annotations

import importlib.util
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pg8000 import DatabaseError
from pg8000.native import Connection

from .migration_base import Migration

if TYPE_CHECKING:
    from types import ModuleType

    from .db_config import PostgresDbConfig

_MIGRATIONS_DIR = Path(__file__).parent / "sql" / "migrations"


# START_CONTRACT: _prefix_id
#   PURPOSE: Extract the prefix_id (token before the first '_') from a migration filename.
#   INPUTS: { filename: Path - migration file path; only filename.name is used }
#   OUTPUTS: { str - the prefix_id token }
#   SIDE_EFFECTS: None
#   LINKS: _pending, _scan_migrations
# END_CONTRACT: _prefix_id
def _prefix_id(filename: Path) -> str:
    return filename.name.split("_", 1)[0]


# START_CONTRACT: _scan_migrations
#   PURPOSE: List all .sql and .py migration files under _MIGRATIONS_DIR, sorted by filename (string sort).
#   INPUTS: { None }
#   OUTPUTS: { list[Path] - sorted migration file paths }
#   SIDE_EFFECTS: None — reads the directory only
#   LINKS: _prefix_id, apply_migrations
# END_CONTRACT: _scan_migrations
def _scan_migrations() -> list[Path]:
    files = list(_MIGRATIONS_DIR.glob("*.sql")) + list(_MIGRATIONS_DIR.glob("*.py"))
    return sorted(files, key=lambda f: f.name)


# START_CONTRACT: _last_applied
#   PURPOSE: Read the highest recorded migration_id from yascheduler_migrations; None means "apply all".
#   INPUTS: { conn: Connection - open pg8000 native connection }
#   OUTPUTS: { str | None - MAX(migration_id), or None when the tracker is empty or (defensively) absent }
#   SIDE_EFFECTS: None — read-only query
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


# START_CONTRACT: _rollback
#   PURPOSE: Best-effort ROLLBACK; swallows any error because the connection may be in a bad state.
#   INPUTS: { conn: Connection - open pg8000 native connection (may be in an aborted txn) }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Issues ROLLBACK on the connection (may itself fail; the failure is swallowed)
#   LINKS: _apply_sql_migration, _apply_py_migration
# END_CONTRACT: _rollback
def _rollback(conn: Connection) -> None:
    # START_BLOCK_ROLLBACK
    try:
        conn.run("ROLLBACK")
    except Exception:
        pass
    # END_BLOCK_ROLLBACK


# START_CONTRACT: _apply_sql_migration
#   PURPOSE: Apply a .sql migration in one transaction: BEGIN → run full SQL text (multi-statement) → INSERT tracker → COMMIT; ROLLBACK and re-raise on any error.
#   INPUTS: { conn: Connection - open pg8000 native connection, path: Path - .sql migration file, prefix_id: str - the migration's prefix_id, log: logging.Logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Runs the migration's DDL/DML; inserts a row into yascheduler_migrations; opens/closes one transaction
#   LINKS: apply_migrations
# END_CONTRACT: _apply_sql_migration
def _apply_sql_migration(
    conn: Connection, path: Path, prefix_id: str, log: logging.Logger
) -> None:
    conn.run("BEGIN")
    try:
        # START_BLOCK_APPLY_SQL
        conn.run(path.read_text())
        conn.run(
            "INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)",
            p=prefix_id,
        )
        conn.run("COMMIT")
        log.debug(
            "[postgres_migrations][_apply_sql_migration][APPLY_SQL] applied %s",
            prefix_id,
        )
        # END_BLOCK_APPLY_SQL
    except Exception:
        _rollback(conn)
        raise


# START_CONTRACT: _record_py_tracker
#   PURPOSE: Record a .py migration in yascheduler_migrations after migrate() returns, honoring the best-effort atomic contract.
#   INPUTS: { conn: Connection - open pg8000 native connection (transaction may or may not be open), prefix_id: str - the migration's prefix_id, log: logging.Logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: INSERTs a tracker row and COMMITs; may reopen a fresh transaction on a transient DatabaseError
#   LINKS: _apply_py_migration
# END_CONTRACT: _record_py_tracker
def _record_py_tracker(conn: Connection, prefix_id: str, log: logging.Logger) -> None:
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
        log.debug(
            "[postgres_migrations][_record_py_tracker][TRACKER_RECORD] "
            "reopen txn for tracker record after %r",
            exc,
        )
        conn.run("BEGIN")
        conn.run(
            "INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)",
            p=prefix_id,
        )
        conn.run("COMMIT")
    log.debug(
        "[postgres_migrations][_record_py_tracker][TRACKER_RECORD] recorded %s",
        prefix_id,
    )
    # END_BLOCK_TRACKER_RECORD


# START_CONTRACT: _apply_py_migration
#   PURPOSE: Apply a .py migration in one transaction: BEGIN → load module → instantiate the single Migration subclass → migrate() → best-effort tracker record; ROLLBACK and re-raise on any error.
#   INPUTS: { conn: Connection - open pg8000 native connection, path: Path - .py migration file, prefix_id: str - the migration's prefix_id (also used as the module name), config: PostgresDbConfig, log: logging.Logger }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Loads and executes a .py module; the migration runs DDL/DML via the injected conn; inserts a row into yascheduler_migrations
#   LINKS: _one_migration_subclass, _record_py_tracker, apply_migrations, M-PERSISTENCE-MIGRATION-BASE
# END_CONTRACT: _apply_py_migration
def _apply_py_migration(
    conn: Connection,
    path: Path,
    prefix_id: str,
    config: PostgresDbConfig,
    log: logging.Logger,
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
        migration = klass(config, conn, log)
        migration.migrate()
        # END_BLOCK_APPLY_PY

        _record_py_tracker(conn, prefix_id, log)
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
    log = logging.getLogger(__name__)
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
        log.debug("[postgres_migrations][apply_migrations][OPEN_CONNECTION] connected")
        # END_BLOCK_OPEN_CONNECTION

        # START_BLOCK_READ_LAST
        last = _last_applied(conn)
        files = _scan_migrations()
        pending = _pending(last, files)
        log.debug(
            "[postgres_migrations][apply_migrations][READ_LAST] last=%s pending=%d",
            last,
            len(pending),
        )
        # END_BLOCK_READ_LAST

        # START_BLOCK_APPLY_PENDING
        for path in pending:
            pid = _prefix_id(path)
            if path.suffix == ".sql":
                _apply_sql_migration(conn, path, pid, log)
            else:
                _apply_py_migration(conn, path, pid, config, log)
            log.debug(
                "[postgres_migrations][apply_migrations][APPLY_PENDING] applied %s", pid
            )
        # END_BLOCK_APPLY_PENDING
    finally:
        # START_BLOCK_CLOSE
        if conn is not None:
            conn.close()
            log.debug(
                "[postgres_migrations][apply_migrations][CLOSE] connection closed"
            )
        # END_BLOCK_CLOSE
