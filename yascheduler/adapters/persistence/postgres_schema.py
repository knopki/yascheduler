# FILE: yascheduler/adapters/persistence/postgres_schema.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Synchronous, transactional application of schema.sql via pg8000.
#   SCOPE: apply_schema() — one-shot schema init for CLI and test fixtures.
#   DEPENDS: M-PERSISTENCE-SQLLOADER, M-CONFIG-DB
#   LINKS: M-PERSISTENCE, M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   apply_schema - apply schema.sql in a BEGIN/COMMIT transaction, rollback on failure
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial creation: sync schema application replacing legacy async DB path.
# END_CHANGE_SUMMARY

import logging

from pg8000 import DatabaseError
from pg8000.native import Connection

from yascheduler.config import ConfigDb

from .sql_loader import load_query

logger = logging.getLogger(__name__)


# START_CONTRACT: apply_schema
#   PURPOSE: Apply schema.sql to a PostgreSQL database in a single transaction.
#   INPUTS: { config: ConfigDb - database connection parameters }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates tables; opens/closes a pg8000 connection; prints on "already exists".
#   LINKS: M-PERSISTENCE-SQLLOADER, M-CONFIG-DB, pg8000.native.Connection
# END_CONTRACT: apply_schema
def apply_schema(config: ConfigDb) -> None:
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
        logger.debug("[postgres_schema][apply_schema][OPEN_CONNECTION] connected")
        # END_BLOCK_OPEN_CONNECTION

        # START_BLOCK_APPLY_SCHEMA
        schema_sql = load_query("schema")
        conn.run("BEGIN")
        conn.run(schema_sql)
        conn.run("COMMIT")
        logger.debug("[postgres_schema][apply_schema][APPLY_SCHEMA] schema applied")
        # END_BLOCK_APPLY_SCHEMA

    except DatabaseError as e:
        # START_BLOCK_HANDLE_EXISTING
        logger.debug(
            "[postgres_schema][apply_schema][HANDLE_EXISTING] DatabaseError caught"
        )
        if conn is not None:
            try:
                conn.run("ROLLBACK")
            except Exception:
                pass
        if "already exists" in str(e.args[0]):
            print("Database already initialized!")
        raise
        # END_BLOCK_HANDLE_EXISTING

    except BaseException:
        # START_BLOCK_ROLLBACK
        logger.debug("[postgres_schema][apply_schema][ROLLBACK] Rolling back on error")
        if conn is not None:
            try:
                conn.run("ROLLBACK")
            except Exception:
                pass
        raise
        # END_BLOCK_ROLLBACK

    finally:
        # START_BLOCK_CLOSE
        if conn is not None:
            conn.close()
            logger.debug("[postgres_schema][apply_schema][CLOSE] connection closed")
        # END_BLOCK_CLOSE
