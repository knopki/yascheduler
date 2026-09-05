"""Integration test fixtures."""
# region MODULE_CONTRACT
# PURPOSE: Pytest fixtures for PostgreSQL integration tests via testcontainers.
# SCOPE: Session-scoped PostgresContainer + schema init, function-scoped raw pg8000 connection with TRUNCATE teardown, UoW factory.
# DEPENDENCIES: USES API: testcontainers.PostgresContainer
# READS: Docker image (postgres:16-alpine)
# KEYWORDS: PostgresContainer, pg8000, schema init, UoW factory
# endregion MODULE_CONTRACT

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


@pytest.fixture(scope="session")
def _init_schema(
    _db_config: PostgresDbConfig,
) -> None:
    """Apply schema once per session, then apply pending migrations."""
    apply_schema(_db_config)
    apply_migrations(_db_config)


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
