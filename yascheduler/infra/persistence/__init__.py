# FILE: yascheduler/infra/persistence/__init__.py
# VERSION: 1.5.0
# START_MODULE_CONTRACT
#   PURPOSE: Persistence subpackage facade — re-exports persistence symbols for the adapters layer facade.
#   SCOPE: Re-export load_query, UnitOfWorkNotInitializedError, apply_schema, PostgresUnitOfWork, PostgresDbConfig; package marker.
#   DEPENDS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-EXCEPTIONS, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-POSTGRES, M-INFRA-DB-CONFIG
#   LINKS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-POSTGRES, M-PERSISTENCE-SCHEMA, M-INFRA-DB-CONFIG
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   UnitOfWorkNotInitializedError - raised when UoW API is used without entering context
#   apply_schema - apply schema.sql in a transactional block (CLI init)
#   PostgresUnitOfWork - concrete UoW backed by Postgres (consumed by composition root)
#   PostgresDbConfig - PostgreSQL connection params frozen dataclass
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.5.0 - Re-export PostgresDbConfig from .db_config (config-aggregate-to-entrypoints / P4); DB connection config relocated from yascheduler.config to yascheduler.infra.persistence.
#   PREVIOUS_CHANGE: v1.4.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY

from .db_config import PostgresDbConfig
from .exceptions import UnitOfWorkNotInitializedError
from .postgres_schema import apply_schema
from .postgres_uow import PostgresUnitOfWork

__all__ = [
    "PostgresDbConfig",
    "PostgresUnitOfWork",
    "UnitOfWorkNotInitializedError",
    "apply_schema",
]
