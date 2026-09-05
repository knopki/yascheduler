"""Synchronous, transactional application of schema.sql via pg8000."""
# region MODULE_CONTRACT
# PURPOSE: Bootstrap the database schema from scratch (fresh database, test fixtures, CI) in a single transactional apply — idempotent so repeated invocation does not corrupt existing databases.
# SCOPE: One-shot schema.sql application via pg8000 for CLI init and test fixtures.
# DEPENDENCIES: USES API: pg8000.Connection, READS: schema.sql via sql_loader
# KEYWORDS: schema, apply, postgres, ddl
# INVARIANTS:
# - schema.sql is the canonical full latest snapshot of the database — every CREATE TABLE statement includes all current columnsr.
# - apply_schema is the sole consumer of schema.sql; apply_migrations consumes the migration files in sql/migrations/ separately.
# RATIONALE:
# - Q: why is schema.sql maintained as a hand-edited full snapshot instead of being generated from migrations?
#   A: a fresh database must reach the latest schema in a single transactional apply (for CI, test fixtures, and fresh deployments) without replaying every historical migration; maintaining the snapshot by hand is the tradeoff, and the migration edit procedure (see the db-migrations spec) requires updating both schema.sql and the migration files in lockstep.
# endregion MODULE_CONTRACT

import contextlib
import logging

from pg8000 import DatabaseError
from pg8000.native import Connection

from .db_config import PostgresDbConfig
from .sql_loader import load_query

__all__ = ["apply_schema"]
logger = logging.getLogger(__name__)


# region FUNC_apply_schema
# PURPOSE: Bootstrap the database from scratch — apply all DDL in one transaction so CI, test fixtures, and fresh deployments start with a consistent schema without manual setup.
# ENSURES:
# - On success, the database contains every table, enum type, trigger function, and CHECK constraint declared in schema.sql; the bootstrap DO block has either created yascheduler_migrations and seeded it to the latest migration (fresh database), created the tracker without a seed row (legacy database), or left the tracker untouched (modern database); the connection is closed.
# - On any failure, the open transaction is rolled back (best-effort), the original exception is re-raised, and the connection is closed.
# INVARIANTS:
# - Synchronous — opens ONE pg8000 native Connection for the whole apply and closes it in finally.
# - Wraps the entire schema.sql body in a single BEGIN / COMMIT transaction — partial-failure leaves no half-applied schema.
# - On DatabaseError, issues best-effort ROLLBACK, logs "Database already initialized!" when the error message contains "already exists", and re-raises regardless.
# - On any other BaseException, issues best-effort ROLLBACK and re-raises.
# - Closes the connection in finally regardless of outcome.
def apply_schema(config: PostgresDbConfig) -> None:
    """Apply schema."""
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

        # region BLOCK_apply_schema
        schema_sql = load_query("schema")
        conn.run("BEGIN")
        conn.run(schema_sql)
        conn.run("COMMIT")
        # endregion BLOCK_apply_schema

    except DatabaseError as e:
        # region BLOCK_handle_existing
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.run("ROLLBACK")
        if "already exists" in str(e.args[0]):
            logger.exception("Database already initialized!")
            logger.debug("ALREADY_EXISTS", extra={"error": str(e)})
        raise
        # endregion BLOCK_handle_existing

    except BaseException:
        # region BLOCK_rollback
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.run("ROLLBACK")
        raise
        # endregion BLOCK_rollback

    finally:
        # region BLOCK_close
        if conn is not None:
            conn.close()
        # endregion BLOCK_close


# endregion FUNC_apply_schema
