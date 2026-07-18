"""Synchronous, transactional application of schema.sql via pg8000."""
# region MODULE_CONTRACT
# PURPOSE: Bootstrap the database schema from scratch (fresh database, test fixtures, CI) in a single transactional apply — idempotent so repeated invocation does not corrupt existing databases.
# SCOPE: One-shot schema.sql application via pg8000 for CLI init and test fixtures.
# DEPENDENCIES: USES API: pg8000.Connection, READS: schema.sql via sql_loader
# KEYWORDS: schema, apply, postgres, ddl
# endregion MODULE_CONTRACT

import contextlib
import logging

from pg8000 import DatabaseError
from pg8000.native import Connection

from .db_config import PostgresDbConfig
from .sql_loader import load_query

logger = logging.getLogger(__name__)

__all__ = ["apply_schema"]


# region FUNC_apply_schema
# PURPOSE: Bootstrap the database from scratch — apply all DDL in one transaction so CI, test fixtures, and fresh deployments start with a consistent schema without manual setup.
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
