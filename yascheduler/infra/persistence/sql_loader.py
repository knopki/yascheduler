# FILE: yascheduler/infra/persistence/sql_loader.py
# VERSION: 1.0.1
# START_MODULE_CONTRACT
#   PURPOSE: SQL query file loader — reads .sql files from the bundled sql/ directory with caching.
#   SCOPE: load_query() with @functools.cache; reads .sql files from bundled sql/ directory.
#   DEPENDS: none
#   LINKS: M-PERSISTENCE-POSTGRES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   load_query - read a named SQL file once (cached)
#   _SQL_DIR - path to the sql/ query directory
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/; no behavioral change.
#   PREVIOUS_CHANGE: v1.0.0 - Extract load_query from __init__.py into dedicated module.
# END_CHANGE_SUMMARY

import functools
from pathlib import Path

_SQL_DIR = Path(__file__).parent / "sql"


# START_CONTRACT: load_query
#   PURPOSE: Load a named SQL query file. The result is cached so the file is
#            read from disk at most once per process lifetime.
#   INPUTS: { name: str - query name in dotted-path form, e.g. "task/get_by_id" }
#   OUTPUTS: { str - the full SQL text of the named file }
#   SIDE_EFFECTS: Reads SQL file from disk on first call per process.
#   LINKS: functools.cache
# END_CONTRACT: load_query
@functools.cache
def load_query(name: str) -> str:
    """Return the content of infra/persistence/sql/<name>.sql."""
    path = _SQL_DIR / f"{name}.sql"
    return path.read_text()
