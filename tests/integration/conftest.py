# FILE: tests/integration/conftest.py
# VERSION: 1.4.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Pytest fixtures for PostgreSQL integration tests via testcontainers.
#   SCOPE: Session-scoped PostgresContainer + schema init, function-scoped raw pg8000 connection with TRUNCATE teardown, UoW factory.
#   DEPENDS: M-INFRA-DB-CONFIG, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-UOW, M-APPLICATION-MESSAGE-BUS, M-PERSISTENCE-POSTGRES
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-UOW, M-APPLICATION-MESSAGE-BUS, M-PERSISTENCE-POSTGRES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   postgres_container - session-scoped fixture: starts postgres:16-alpine container
#   _db_config - session-scoped fixture: parses container URL into PostgresDbConfig
#   _init_schema - session-scoped fixture: applies schema.sql then pending migrations once
#   _bus - session-scoped fixture: bare MessageBus (no-op dispatch)
#   pg_executor - function-scoped fixture: ThreadPoolExecutor(max_workers=1)
#   pg_conn - function-scoped fixture: raw pg8000 connection, TRUNCATE + close on teardown
#   uow_factory - function-scoped fixture: Callable[[], PostgresUnitOfWork]
#   pytest_collection_modifyitems - auto-mark all tests as "integration"
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - _init_schema applies pending migrations via apply_migrations after apply_schema (add-db-migrations).
#   PREVIOUS_CHANGE: v1.3.0 - Replace DB fixture with layered pg_conn/pg_executor/uow_factory fixtures (remove-legacy-db).
# END_CHANGE_SUMMARY

"""Integration test fixtures."""

from collections.abc import AsyncGenerator, Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import pg8000.native
import pytest
from testcontainers.postgres import PostgresContainer

from yascheduler.application import MessageBus
from yascheduler.infra.persistence import PostgresDbConfig, apply_migrations
from yascheduler.infra.persistence.postgres_schema import apply_schema
from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/tests/integration/" in str(item.path):
            item.add_marker("integration")


# START_CONTRACT: postgres_container
#   PURPOSE: Start a PostgreSQL 16 Alpine container via testcontainers, shared across the session.
#   INPUTS: { None }
#   OUTPUTS: { Generator[PostgresContainer] - running container }
#   SIDE_EFFECTS: Starts Docker container; container stops on session teardown
#   LINKS: M-PERSISTENCE-SCHEMA
# END_CONTRACT: postgres_container
@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Session-scoped PostgreSQL container from testcontainers."""
    with PostgresContainer("docker.io/library/postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def _db_config(postgres_container: PostgresContainer) -> PostgresDbConfig:
    """Parse container connection URL into PostgresDbConfig (session-scoped)."""
    url = urlparse(postgres_container.get_connection_url())
    return PostgresDbConfig(
        user=url.username or "test",
        password=url.password or "test",
        database=url.path.lstrip("/"),
        host=url.hostname or "localhost",
        port=url.port or 5432,
    )


# START_CONTRACT: _init_schema
#   PURPOSE: Apply schema.sql then pending migrations once per session so per-test DB connections start with the latest schema.
#   INPUTS: { _db_config: PostgresDbConfig }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates yascheduler_nodes/yascheduler_tasks tables and yascheduler_migrations tracker; applies pending migrations
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: _init_schema
@pytest.fixture(scope="session")
def _init_schema(
    _db_config: PostgresDbConfig,
) -> None:
    """Apply schema once per session, then apply pending migrations."""
    apply_schema(_db_config)
    apply_migrations(_db_config)


# START_CONTRACT: _bus
#   PURPOSE: Provide a session-scoped bare MessageBus (no-op dispatch).
#   INPUTS: { None }
#   OUTPUTS: { MessageBus }
#   SIDE_EFFECTS: None
# END_CONTRACT: _bus
@pytest.fixture(scope="session")
def _bus() -> MessageBus:
    """Session-scoped bare MessageBus (no-op dispatch)."""
    return MessageBus()


@pytest.fixture
def pg_executor() -> Generator[ThreadPoolExecutor, None, None]:
    """Function-scoped single-worker thread pool executor."""
    executor = ThreadPoolExecutor(max_workers=1)
    yield executor
    executor.shutdown(wait=False)


# START_CONTRACT: pg_conn
#   PURPOSE: Provide a function-scoped raw pg8000 connection; TRUNCATE + close on teardown.
#   INPUTS: { _db_config: PostgresDbConfig, _init_schema: None, pg_executor: ThreadPoolExecutor }
#   OUTPUTS: { AsyncGenerator[pg8000.native.Connection] - raw connection }
#   SIDE_EFFECTS: Opens per-test pg8000 connection, TRUNCATEs tables, closes connection and shuts down executor on teardown
#   LINKS: M-CONFIG-DB
# END_CONTRACT: pg_conn
@pytest.fixture
async def pg_conn(
    _db_config: PostgresDbConfig,
    _init_schema: None,
    pg_executor: ThreadPoolExecutor,
) -> AsyncGenerator[pg8000.native.Connection, None]:
    """Per-test raw pg8000 connection; TRUNCATE tables on teardown."""
    conn = pg8000.native.Connection(
        user=_db_config.user,
        host=_db_config.host,
        database=_db_config.database,
        port=_db_config.port,
        password=_db_config.password,
    )
    yield conn
    conn.run("TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE")
    conn.close()
    pg_executor.shutdown(wait=False)


# START_CONTRACT: uow_factory
#   PURPOSE: Provide a function-scoped factory for PostgresUnitOfWork instances.
#   INPUTS: { _db_config: PostgresDbConfig, _init_schema: None, _bus: MessageBus }
#   OUTPUTS: { Callable[[], PostgresUnitOfWork] }
#   SIDE_EFFECTS: None
#   LINKS: M-PERSISTENCE-UOW, M-APPLICATION-MESSAGE-BUS
# END_CONTRACT: uow_factory
@pytest.fixture
def uow_factory(
    _db_config: PostgresDbConfig,
    _init_schema: None,
    _bus: MessageBus,
    pg_conn: pg8000.native.Connection,
) -> Callable[[], PostgresUnitOfWork]:
    """Return a factory that creates PostgresUnitOfWork instances.

    Depends on pg_conn to ensure tables are TRUNCATEd between tests.
    """
    # pg_conn dependency ensures per-test TRUNCATE via its teardown chain
    _ = pg_conn

    def _factory() -> PostgresUnitOfWork:
        return PostgresUnitOfWork(_db_config, _bus)

    return _factory
