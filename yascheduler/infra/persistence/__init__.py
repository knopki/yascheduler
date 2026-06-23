# FILE: yascheduler/infra/persistence/__init__.py
# VERSION: 1.4.1
# START_MODULE_CONTRACT
#   PURPOSE: Persistence subpackage facade — re-exports persistence symbols for the adapters layer facade.
#   SCOPE: Re-export load_query, UnitOfWorkNotInitializedError, apply_schema, PostgresUnitOfWork; package marker.
#   DEPENDS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-EXCEPTIONS, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-POSTGRES
#   LINKS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-POSTGRES, M-PERSISTENCE-SCHEMA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   UnitOfWorkNotInitializedError - raised when UoW API is used without entering context
#   apply_schema - apply schema.sql in a transactional block (CLI init)
#   PostgresUnitOfWork - concrete UoW backed by Postgres (consumed by composition root)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.4.0 - Re-export PostgresUnitOfWork from postgres_uow (clean-architecture-imports R2 — composition root wiring).
# END_CHANGE_SUMMARY

from .exceptions import UnitOfWorkNotInitializedError
from .postgres_schema import apply_schema
from .postgres_uow import PostgresUnitOfWork

__all__ = [
    "PostgresUnitOfWork",
    "UnitOfWorkNotInitializedError",
    "apply_schema",
]
