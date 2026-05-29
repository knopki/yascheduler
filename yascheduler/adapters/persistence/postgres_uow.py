# FILE: yascheduler/adapters/persistence/postgres_uow.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Unit of Work implementation for PostgreSQL using pg8000.
#   SCOPE: PostgresUnitOfWork managing transactions, repositories, and connection lifecycle.
#   DEPENDS: M-PERSISTENCE-POSTGRES, M-CONFIG-DB
#   LINKS: M-PERSISTENCE-POSTGRES, M-CONFIG-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   PostgresUnitOfWork - async context manager providing tasks and node repositories
#   _require_conn - guard returning Connection or raising RuntimeError
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Add docstrings; use conn.run('COMMIT'/'ROLLBACK') to avoid stub gaps.
#   PREVIOUS_CHANGE: v1.0.1 - Replace asserts with _require_conn() for proper runtime errors and type narrowing.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from pg8000.native import Connection

from yascheduler.config import ConfigDb

from .postgres import PostgresNodeRepository, PostgresTaskRepository

T = TypeVar("T")


# START_CONTRACT: PostgresUnitOfWork
#   PURPOSE: Async context manager that manages a pg8000 connection and exposes
#            task and node repositories operating on the same transaction.
#   INPUTS: { config: ConfigDb - database connection parameters }
#   OUTPUTS: { PostgresUnitOfWork - self from __aenter__ }
#   SIDE_EFFECTS: Creates and closes pg8000 connections; manages a ThreadPoolExecutor.
#   LINKS: PostgresTaskRepository, PostgresNodeRepository, ConfigDb, pg8000.native.Connection
# END_CONTRACT: PostgresUnitOfWork
class PostgresUnitOfWork:
    """Async context manager for PostgreSQL transactional boundaries."""

    # START_CONTRACT: PostgresUnitOfWork.__init__
    #   PURPOSE: Initialise UoW with config and a single-worker thread pool.
    #   INPUTS: { config: ConfigDb - database connection parameters }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates a ThreadPoolExecutor(max_workers=1).
    #   LINKS: ThreadPoolExecutor, ConfigDb
    # END_CONTRACT: PostgresUnitOfWork.__init__
    def __init__(self, config: ConfigDb) -> None:
        self._config = config
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._conn: Connection | None = None
        self.tasks: PostgresTaskRepository | None = None
        self.nodes: PostgresNodeRepository | None = None

    # START_CONTRACT: PostgresUnitOfWork.__aenter__
    #   PURPOSE: Create a pg8000 connection and instantiate repositories.
    #   INPUTS: { None }
    #   OUTPUTS: { PostgresUnitOfWork - self }
    #   SIDE_EFFECTS: Opens a real PostgreSQL connection via pg8000.
    #   LINKS: _create_connection, PostgresTaskRepository, PostgresNodeRepository
    # END_CONTRACT: PostgresUnitOfWork.__aenter__
    async def __aenter__(self) -> PostgresUnitOfWork:
        """Open connection, begin transaction, wire repositories."""
        loop = asyncio.get_running_loop()
        try:
            self._conn = await loop.run_in_executor(
                self._executor, self._create_connection
            )
            await loop.run_in_executor(self._executor, lambda: self._conn.run("BEGIN"))
            self.tasks = PostgresTaskRepository(self._conn, self._executor)
            self.nodes = PostgresNodeRepository(self._conn, self._executor)
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
        exc_tb: Any | None,
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
    #   PURPOSE: Commit the current transaction synchronously via the thread pool.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Commits the pg8000 connection transaction.
    #   LINKS: _require_conn, _run_sync
    # END_CONTRACT: PostgresUnitOfWork.commit
    async def commit(self) -> None:
        """Commit the transaction."""
        conn = self._require_conn()
        await self._run_sync(lambda: conn.run("COMMIT"))

    # START_CONTRACT: PostgresUnitOfWork.rollback
    #   PURPOSE: Roll back the current transaction synchronously via the thread pool.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Rolls back the pg8000 connection transaction.
    #   LINKS: _require_conn, _run_sync
    # END_CONTRACT: PostgresUnitOfWork.rollback
    async def rollback(self) -> None:
        """Rollback the transaction."""
        conn = self._require_conn()
        await self._run_sync(lambda: conn.run("ROLLBACK"))

    # START_CONTRACT: _require_conn
    #   PURPOSE: Return the active connection or raise if UoW was not entered.
    #   INPUTS: { None }
    #   OUTPUTS: { Connection - the active pg8000 connection }
    #   SIDE_EFFECTS: None
    #   LINKS: pg8000.native.Connection
    # END_CONTRACT: _require_conn
    def _require_conn(self) -> Connection:
        """Return active connection, or raise if not yet entered."""
        if self._conn is None:
            raise RuntimeError(
                "Connection not initialized; use 'async with' to enter the UoW"
            )
        return self._conn

    # START_CONTRACT: _create_connection
    #   PURPOSE: Create a new synchronous pg8000 connection from config.
    #   INPUTS: { None }
    #   OUTPUTS: { Connection - a new pg8000 native connection }
    #   SIDE_EFFECTS: Opens a TCP connection to PostgreSQL.
    #   LINKS: pg8000.native.Connection, ConfigDb
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

    # START_CONTRACT: _run_sync
    #   PURPOSE: Run a synchronous function in the thread pool executor.
    #   INPUTS: { fn: Callable[[], T] - synchronous callable }
    #   OUTPUTS: { T - the return value of fn }
    #   SIDE_EFFECTS: Executes fn in a separate thread.
    #   LINKS: asyncio.loop.run_in_executor
    # END_CONTRACT: _run_sync
    async def _run_sync(self, fn: Callable[[], T]) -> T:
        """Execute fn in the thread pool, return its result."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn)
