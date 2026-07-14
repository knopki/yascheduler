# FILE: yascheduler/infra/persistence/postgres_uow.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit of Work implementation for PostgreSQL using pg8000.
#   SCOPE: PostgresUnitOfWork managing transaction lifecycle, repository wiring, event collection and dispatch.
#   DEPENDS: M-PERSISTENCE-POSTGRES, M-INFRA-DB-CONFIG, M-PERSISTENCE-EXCEPTIONS, M-APPLICATION-MESSAGE-BUS, M-DOMAIN-EVENTS
#   LINKS: M-PERSISTENCE-POSTGRES, M-INFRA-DB-CONFIG, M-APPLICATION-MESSAGE-BUS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   PostgresUnitOfWork - async context manager providing tasks and node repositories with event dispatch
#   _require_conn - guard returning Connection or raising UnitOfWorkNotInitializedError
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - reform-grace-logging: strip grace marker from commit event-dispatch exception (pure narrative).
#   PREVIOUS_CHANGE: v1.6.0 - collect_events reads task.events directly and clears _saved_tasks.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, TypeVar

from pg8000.native import Connection

from yascheduler.shared import get_logger

from .exceptions import UnitOfWorkNotInitializedError
from .postgres import PostgresNodeRepository, PostgresTaskRepository

if TYPE_CHECKING:
    import types
    from collections.abc import Callable

    from yascheduler.application import MessageBus
    from yascheduler.domain import DomainEvent, Task

    from .db_config import PostgresDbConfig

T = TypeVar("T")

logger = get_logger("M-PERSISTENCE-UOW")


# START_CONTRACT: PostgresUnitOfWork
#   PURPOSE: Async context manager that manages a pg8000 connection and exposes
#            task and node repositories operating on the same transaction.
#   INPUTS: { config: PostgresDbConfig - database connection parameters }
#   OUTPUTS: { PostgresUnitOfWork - self from __aenter__ }
#   SIDE_EFFECTS: Creates and closes pg8000 connections; manages a ThreadPoolExecutor.
#   LINKS: PostgresTaskRepository, PostgresNodeRepository, PostgresDbConfig, pg8000.native.Connection
# END_CONTRACT: PostgresUnitOfWork
class PostgresUnitOfWork:
    """Async context manager for PostgreSQL transactional boundaries."""

    # START_CONTRACT: PostgresUnitOfWork.__init__
    #   PURPOSE: Initialise UoW with config and a single-worker thread pool.
    #   INPUTS: { config: PostgresDbConfig - database connection parameters }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates a ThreadPoolExecutor(max_workers=1).
    #   LINKS: ThreadPoolExecutor, PostgresDbConfig
    # END_CONTRACT: PostgresUnitOfWork.__init__
    def __init__(self, config: PostgresDbConfig, bus: MessageBus) -> None:
        # FIXME: no backoff.on_exception on InterfaceError
        self._config = config
        self._bus = bus
        self._saved_tasks: list[Task] = []
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._conn: Connection | None = None
        self._tasks: PostgresTaskRepository | None = None
        self._nodes: PostgresNodeRepository | None = None

    @property
    def tasks(self) -> PostgresTaskRepository:
        if self._tasks is None:
            raise UnitOfWorkNotInitializedError(
                "UoW not entered; use 'async with' to access repositories"
            )
        return self._tasks

    @property
    def nodes(self) -> PostgresNodeRepository:
        if self._nodes is None:
            raise UnitOfWorkNotInitializedError(
                "UoW not entered; use 'async with' to access repositories"
            )
        return self._nodes

    # START_CONTRACT: PostgresUnitOfWork.__aenter__
    #   PURPOSE: Create a pg8000 connection and instantiate repositories.
    #   INPUTS: { None }
    #   OUTPUTS: { PostgresUnitOfWork - self }
    #   SIDE_EFFECTS: Opens a real PostgreSQL connection via pg8000.
    #   LINKS: _create_connection, PostgresTaskRepository, PostgresNodeRepository
    # END_CONTRACT: PostgresUnitOfWork.__aenter__
    async def __aenter__(self) -> PostgresUnitOfWork:
        """Open connection, begin transaction, wire repositories."""
        self._saved_tasks = []
        loop = asyncio.get_running_loop()
        try:
            self._conn = await loop.run_in_executor(
                self._executor, self._create_connection
            )
            await loop.run_in_executor(self._executor, lambda: self._conn.run("BEGIN"))
            self._tasks = PostgresTaskRepository(
                self._conn, self._executor, self._saved_tasks
            )
            self._nodes = PostgresNodeRepository(self._conn, self._executor)
        except BaseException:
            if self._conn is not None:
                try:
                    await loop.run_in_executor(self._executor, self._conn.close)
                except Exception:
                    pass
            self._executor.shutdown(wait=False)
            raise
        return self

    # START_CONTRACT: PostgresUnitOfWork.__aexit__
    #   PURPOSE: Close the connection and shut down the executor; rollback on exception.
    #   INPUTS: { exc_type, exc_val, exc_tb - exception info from the context body }
    #   OUTPUTS: { bool - False to propagate any exception }
    #   SIDE_EFFECTS: Rolls back if exception occurred; closes connection; shuts down executor.
    #   LINKS: rollback, _require_conn, Connection.close, ThreadPoolExecutor.shutdown
    # END_CONTRACT: PostgresUnitOfWork.__aexit__
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        """Rollback on error, close connection, shutdown executor."""
        if exc_type is not None and self._conn is not None:
            try:
                await self.rollback()
            except Exception:
                pass
        if self._conn is not None:
            try:
                await self._run_sync(self._conn.close)
            except Exception:
                pass
        self._executor.shutdown(wait=False)
        self._conn = None
        return False

    # START_CONTRACT: PostgresUnitOfWork.commit
    #   PURPOSE: Commit the current transaction and dispatch collected events.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Commits the pg8000 connection transaction; dispatches domain events via MessageBus.
    #   LINKS: _require_conn, _run_sync, publish_events
    # END_CONTRACT: PostgresUnitOfWork.commit
    async def commit(self) -> None:
        """Commit the transaction and dispatch collected events."""
        conn = self._require_conn()
        await self._run_sync(lambda: conn.run("COMMIT"))
        try:
            await self.publish_events()
        except Exception:
            logger.exception("event dispatch failed after commit")

    # START_CONTRACT: PostgresUnitOfWork.rollback
    #   PURPOSE: Roll back the current transaction and discard collected events.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Rolls back the pg8000 connection transaction; clears saved tasks.
    #   LINKS: _require_conn, _run_sync
    # END_CONTRACT: PostgresUnitOfWork.rollback
    async def rollback(self) -> None:
        """Rollback the transaction and discard events."""
        conn = self._require_conn()
        await self._run_sync(lambda: conn.run("ROLLBACK"))
        self._saved_tasks.clear()

    # START_CONTRACT: PostgresUnitOfWork.collect_events
    #   PURPOSE: Read events from all saved aggregates via the public events field and clear _saved_tasks.
    #   INPUTS: { None }
    #   OUTPUTS: { list[DomainEvent] - flat list of all collected events }
    #   SIDE_EFFECTS: None — internal state only.
    #   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
    # END_CONTRACT: PostgresUnitOfWork.collect_events
    async def collect_events(self) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for task in self._saved_tasks:
            events.extend(task.events)
        self._saved_tasks.clear()
        return events

    # START_CONTRACT: PostgresUnitOfWork.publish_events
    #   PURPOSE: Collect events and dispatch them via the message bus.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Dispatches events via MessageBus.
    #   LINKS: M-APPLICATION-MESSAGE-BUS
    # END_CONTRACT: PostgresUnitOfWork.publish_events
    async def publish_events(self) -> None:
        events = await self.collect_events()
        await self._bus.dispatch(events)
        self._saved_tasks.clear()

    # START_CONTRACT: _create_connection

    def _require_conn(self) -> Connection:
        """Return active connection, or raise if not yet entered."""
        if self._conn is None:
            raise UnitOfWorkNotInitializedError(
                "Connection not initialized; use 'async with' to enter the UoW"
            )
        return self._conn

    # START_CONTRACT: _create_connection
    #   PURPOSE: Create a new synchronous pg8000 connection from config.
    #   INPUTS: { None }
    #   OUTPUTS: { Connection - a new pg8000 native connection }
    #   SIDE_EFFECTS: Opens a TCP connection to PostgreSQL.
    #   LINKS: pg8000.native.Connection, PostgresDbConfig
    # END_CONTRACT: _create_connection
    def _create_connection(self) -> Connection:
        """Create a new pg8000 connection from config."""
        return Connection(
            user=self._config.user,
            host=self._config.host,
            database=self._config.database,
            port=self._config.port,
            password=self._config.password,
        )

    async def _run_sync(self, fn: Callable[[], T]) -> T:
        """Execute fn in the thread pool, return its result."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn)
