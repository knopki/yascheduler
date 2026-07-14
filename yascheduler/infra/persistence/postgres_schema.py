# FILE: yascheduler/infra/persistence/postgres_schema.py
# VERSION: 1.0.1
# START_MODULE_CONTRACT
#   PURPOSE: Synchronous, transactional application of schema.sql via pg8000.
#   SCOPE: One-shot schema.sql application via pg8000 for CLI init and test fixtures.
#   DEPENDS: M-PERSISTENCE-SQLLOADER, M-INFRA-DB-CONFIG
#   LINKS: M-PERSISTENCE, M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   apply_schema - apply schema.sql in a BEGIN/COMMIT transaction, rollback on failure
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Import PostgresDbConfig from .db_config intra-package instead of ConfigDb from yascheduler.config.
#   PREVIOUS_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/; no behavioral change.
# END_CHANGE_SUMMARY


from pg8000 import DatabaseError
from pg8000.native import Connection

from yascheduler.shared import get_logger

from .db_config import PostgresDbConfig
from .sql_loader import load_query

logger = get_logger("M-PERSISTENCE-SCHEMA")


# START_CONTRACT: apply_schema
#   PURPOSE: Apply schema.sql to a PostgreSQL database in a single transaction.
#   INPUTS: { config: PostgresDbConfig - database connection parameters }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates tables; opens/closes a pg8000 connection; prints on "already exists".
#   LINKS: M-PERSISTENCE-SQLLOADER, M-INFRA-DB-CONFIG, pg8000.native.Connection
# END_CONTRACT: apply_schema
def apply_schema(config: PostgresDbConfig) -> None:
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

        # START_BLOCK_APPLY_SCHEMA
        schema_sql = load_query("schema")
        conn.run("BEGIN")
        conn.run(schema_sql)
        conn.run("COMMIT")
        logger.trace("APPLY_SCHEMA")
        # END_BLOCK_APPLY_SCHEMA

    except DatabaseError as e:
        # START_BLOCK_HANDLE_EXISTING
        logger.trace("HANDLE_EXISTING")
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
        logger.trace("ROLLBACK")
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
            logger.trace("CLOSE")
        # END_BLOCK_CLOSE
