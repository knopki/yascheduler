"""SQL query file loader — reads .sql files from the bundled sql/ directory with caching."""
# region MODULE_CONTRACT
# PURPOSE: Load named .sql query files once with caching so persistence repositories work with string SQL without duplicating path resolution or disk I/O per call.
# SCOPE: load_query() with @functools.cache; reads .sql files from bundled sql/ directory.
# DEPENDENCIES: READS: .sql files from the bundled sql/ directory on first call
# KEYWORDS: sql, loader, query, cache
# endregion MODULE_CONTRACT

from functools import cache
from pathlib import Path

__all__ = ["load_query"]

_SQL_DIR = Path(__file__).parent / "sql"


# region FUNC_load_query
# PURPOSE: Provide idempotent SQL query access so repositories and schema utilities get SQL strings without duplicating path resolution or disk I/O per call.
@cache
def load_query(name: str) -> str:
    """Return the content of infra/persistence/sql/<name>.sql."""
    path = _SQL_DIR / f"{name}.sql"
    return path.read_text()


# endregion FUNC_load_query
