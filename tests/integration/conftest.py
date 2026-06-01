# FILE: tests/integration/conftest.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Pytest fixtures for PostgreSQL integration tests via testcontainers.
#   SCOPE: Session-scoped PostgresContainer + schema init, function-scoped DB connections, per-test TRUNCATE.
#   DEPENDS: M-DB, M-CONFIG-DB
#   LINKS: M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   postgres_container - session-scoped fixture: starts postgres:16-alpine container
#   _db_config - session-scoped fixture: parses container URL into ConfigDb
#   _init_schema - session-scoped fixture: applies schema.sql and migrate() once
#   db - function-scoped fixture: fresh DB connection per test, TRUNCATE on teardown
#   pytest_collection_modifyitems - auto-mark all tests as "integration"
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Move TRUNCATE into db fixture teardown; remove autouse clean_tables.
#   PREVIOUS_CHANGE: v1.0.0 - Initial integration test infrastructure with testcontainers-postgres.
# END_CHANGE_SUMMARY

"""Integration test fixtures."""

from collections.abc import AsyncGenerator, Generator
from urllib.parse import urlparse

import pytest
from testcontainers.postgres import PostgresContainer

from yascheduler.config.db import ConfigDb
from yascheduler.db import DB


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/tests/integration/" in str(item.path):
            item.add_marker("integration")


# START_CONTRACT: postgres_container
#   PURPOSE: Start a PostgreSQL 16 Alpine container via testcontainers, shared across the session.
#   INPUTS: { None }
#   OUTPUTS: { Generator[PostgresContainer] - running container }
#   SIDE_EFFECTS: Starts Docker container; container stops on session teardown
#   LINKS: M-DB
# END_CONTRACT: postgres_container
@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Session-scoped PostgreSQL container from testcontainers."""
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def _db_config(postgres_container: PostgresContainer) -> ConfigDb:
    """Parse container connection URL into ConfigDb (session-scoped)."""
    url = urlparse(postgres_container.get_connection_url())
    return ConfigDb(
        user=url.username or "test",
        password=url.password or "test",
        database=url.path.lstrip("/"),
        host=url.hostname or "localhost",
        port=url.port or 5432,
    )


# START_CONTRACT: _init_schema
#   PURPOSE: Apply schema.sql and migrate() once per session so per-test DB connections start with ready tables.
#   INPUTS: { postgres_container: PostgresContainer, _db_config: ConfigDb }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates yascheduler_nodes/yascheduler_tasks tables, runs ALTER TABLE migrations
#   LINKS: M-DB
# END_CONTRACT: _init_schema
@pytest.fixture(scope="session")
async def _init_schema(
    postgres_container: PostgresContainer,
    _db_config: ConfigDb,
) -> None:
    """Apply schema and migration once per session."""
    from pathlib import Path

    instance = await DB.create(_db_config, automigrate=False)
    schema_path = (
        Path(__file__).resolve().parent.parent.parent  # noqa: ASYNC240
        / "yascheduler"
        / "adapters"
        / "persistence"
        / "sql"
        / "schema.sql"
    )
    await instance.run(schema_path.read_text())
    await instance.migrate()
    await instance.close()


# START_CONTRACT: db
#   PURPOSE: Provide a function-scoped DB connection to the session-scoped PostgreSQL container.
#   INPUTS: { _db_config: ConfigDb, _init_schema: None }
#   OUTPUTS: { AsyncGenerator[DB] - live database instance }
#   SIDE_EFFECTS: Opens per-test DB connection, TRUNCATEs tables, closes on teardown
#   LINKS: M-DB, M-CONFIG-DB
# END_CONTRACT: db
@pytest.fixture
async def db(
    _db_config: ConfigDb,
    _init_schema: None,
) -> AsyncGenerator[DB, None]:
    """Per-test DB connection to testcontainer PostgreSQL."""
    instance = await DB.create(_db_config, automigrate=False)
    yield instance
    await instance.run("TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE")
    await instance.close()
