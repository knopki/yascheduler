# FILE: yascheduler/infra/persistence/__init__.py
# VERSION: 1.7.0
# START_MODULE_CONTRACT
#   PURPOSE: Persistence subpackage facade — re-exports persistence symbols for the adapters layer facade.
#   SCOPE: Re-export load_query, UnitOfWorkNotInitializedError, TaskRowNotFoundError, apply_schema, apply_migrations, PostgresUnitOfWork, PostgresDbConfig; package marker.
#   DEPENDS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-EXCEPTIONS, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS, M-PERSISTENCE-POSTGRES, M-INFRA-DB-CONFIG
#   LINKS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-POSTGRES, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS, M-INFRA-DB-CONFIG
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   UnitOfWorkNotInitializedError - raised when UoW API is used without entering context
#   TaskRowNotFoundError - raised by PostgresTaskRepository.save/update_status when an UPDATE targets a non-existent task_id
#   apply_schema - apply schema.sql in a transactional block (CLI init)
#   apply_migrations - apply pending .sql/.py migrations from sql/migrations/ (CLI init)
#   PostgresUnitOfWork - concrete UoW backed by Postgres (consumed by composition root)
#   PostgresDbConfig - PostgreSQL connection params frozen dataclass
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Re-export apply_migrations from .postgres_migrations (add-db-migrations).
#   PREVIOUS_CHANGE: v1.6.0 - Re-export TaskRowNotFoundError from .exceptions (fix-save-silent-zero-rows).
# END_CHANGE_SUMMARY

from .db_config import PostgresDbConfig
from .exceptions import TaskRowNotFoundError, UnitOfWorkNotInitializedError
from .postgres_migrations import apply_migrations
from .postgres_schema import apply_schema
from .postgres_uow import PostgresUnitOfWork

__all__ = [
    "PostgresDbConfig",
    "PostgresUnitOfWork",
    "TaskRowNotFoundError",
    "UnitOfWorkNotInitializedError",
    "apply_migrations",
    "apply_schema",
]
