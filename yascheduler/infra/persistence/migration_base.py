# FILE: yascheduler/infra/persistence/migration_base.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Migration base class for .py migrations with injected config/conn/log and begin()/commit() helpers.
#   SCOPE: Migration base class for .py migration subclasses; runner instantiates with (config, conn, log).
#   DEPENDS: M-INFRA-DB-CONFIG, M-PERSISTENCE
#   LINKS: M-PERSISTENCE-MIGRATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Migration - base class for .py database migrations; instantiated by the runner with (config, conn, log)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Introduce Migration base class for .py migrations. Subclasses receive injected config/conn/log and use begin()/commit() for non-transactional ops (CREATE INDEX CONCURRENTLY, VACUUM).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger

    from pg8000.native import Connection

    from .db_config import PostgresDbConfig


class Migration:
    """Base class for ``.py`` database migrations.

    The runner instantiates exactly one subclass per ``.py`` migration file
    with ``(config, conn, log)`` and calls ``migrate()`` inside an open
    transaction. Subclasses use ``self.config``, ``self.conn``, and
    ``self.log`` directly.

    For migrations needing non-transactional operations
    (``CREATE INDEX CONCURRENTLY``, ``VACUUM``), use ``self.commit()`` to close
    the runner's transaction, run the command, then ``self.begin()`` to reopen
    one. Migrations are NOT required to be idempotent: the
    ``yascheduler_migrations`` tracker guards against re-application.
    """

    # START_CONTRACT: Migration
    #   PURPOSE: Base class injected with (config, conn, log); subclass implements migrate().
    #   INPUTS: { config: PostgresDbConfig - DB connection params, conn: pg8000.native.Connection - open connection (runner has issued BEGIN), log: logging.Logger - migration-scoped logger }
    #   OUTPUTS: { None - subclass migrate() performs DDL/DML via self.conn }
    #   SIDE_EFFECTS: None in the base class; subclasses run DDL/DML via self.conn.
    #   LINKS: M-PERSISTENCE-MIGRATIONS (runner instantiates subclasses), M-INFRA-DB-CONFIG, pg8000.native.Connection
    # END_CONTRACT: Migration
    def __init__(
        self,
        config: PostgresDbConfig,
        conn: Connection,
        log: Logger,
    ) -> None:
        self.config = config
        self.conn = conn
        self.log = log

    def begin(self) -> None:
        """Issue ``BEGIN`` on the wrapped connection."""
        self.conn.run("BEGIN")

    def commit(self) -> None:
        """Issue ``COMMIT`` on the wrapped connection."""
        self.conn.run("COMMIT")

    def migrate(self) -> None:
        raise NotImplementedError
