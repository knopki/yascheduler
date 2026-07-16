"""Migration base class for .py migrations with injected config/conn/log and begin()/commit() helpers."""
# region MODULE_CONTRACT
# PURPOSE: Provide a minimal contract for Python-based migrations — inject config, connection, and logger so subclasses implement only the migration step without plumbing infrastructure.
# SCOPE: Migration base class for .py migration subclasses; runner instantiates with (config, conn, log).
# DEPENDENCIES: USES API: pg8000.Connection
# KEYWORDS: migration, base class, database migration
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger

    from pg8000.native import Connection

    from .db_config import PostgresDbConfig

__all__ = ["Migration"]


# region CLASS_Migration
# PURPOSE: Define the contract for Python-based migrations — inject config, connection, and logger so subclasses implement only the migration logic without wiring infrastructure.
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
        """Run a single migration step."""
        raise NotImplementedError


# endregion CLASS_Migration
