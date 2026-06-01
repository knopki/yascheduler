# FILE: yascheduler/adapters/persistence/__init__.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Persistence adapter entry point — re-exports from persistence submodules.
#   SCOPE: Re-export load_query, UnitOfWorkNotInitializedError; package marker.
#   DEPENDS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-EXCEPTIONS
#   LINKS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-POSTGRES, M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   load_query - read a named SQL file once (cached), re-exported from sql_loader
#   UnitOfWorkNotInitializedError - raised when UoW API is used without entering context
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Re-export UnitOfWorkNotInitializedError from exceptions.
#   PREVIOUS_CHANGE: v1.1.0 - Extract load_query implementation to sql_loader.py; re-export only.
# END_CHANGE_SUMMARY

from .exceptions import UnitOfWorkNotInitializedError
from .sql_loader import load_query

__all__ = ["load_query", "UnitOfWorkNotInitializedError"]
