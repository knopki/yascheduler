# FILE: yascheduler/adapters/persistence/__init__.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Persistence adapter entry point — re-exports from persistence submodules.
#   SCOPE: Re-export load_query; package marker.
#   DEPENDS: M-PERSISTENCE-SQLLOADER
#   LINKS: M-PERSISTENCE-SQLLOADER, M-PERSISTENCE-POSTGRES, M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   load_query - read a named SQL file once (cached), re-exported from sql_loader
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Extract load_query implementation to sql_loader.py; re-export only.
#   PREVIOUS_CHANGE: v1.0.0 - Add load_query utility for named SQL file resolution.
# END_CHANGE_SUMMARY

from .sql_loader import load_query

__all__ = ["load_query"]
