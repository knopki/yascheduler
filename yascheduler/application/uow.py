"""Abstract Unit of Work Protocol defining the transactional boundary contract for use cases."""
# region MODULE_CONTRACT
# PURPOSE: Define the abstract Unit of Work Protocol that use cases depend on, keeping transaction management decoupled from any persistence implementation.
# SCOPE: AbstractUnitOfWork Protocol — async context manager.
# KEYWORDS: uow, unit of work, protocol, transaction, repository
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import types

    from yascheduler.domain import DomainEvent, NodeRepository, TaskRepository
    from yascheduler.shared import Self

__all__ = [
    "AbstractUnitOfWork",
]


# region CLASS_AbstractUnitOfWork
# PURPOSE: State the contract use cases depend on — transactional access to task/node repositories plus post-commit event dispatch — so use cases stay decoupled from any persistence implementation.
@runtime_checkable
class AbstractUnitOfWork(Protocol):
    """Async context manager providing task and node repositories sharing a transaction."""

    @property
    def tasks(self) -> TaskRepository:
        """Access the task repository within the current transaction."""
        ...

    @property
    def nodes(self) -> NodeRepository:
        """Access the node repository within the current transaction."""
        ...

    async def __aenter__(self) -> Self:
        """Enter the unit of work context."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        """Exit the unit of work context, rolling back on exception."""
        ...

    async def commit(self) -> None:
        """Commit the current transaction."""
        ...

    async def rollback(self) -> None:
        """Roll back the current transaction."""
        ...

    async def collect_events(self) -> list[DomainEvent]:
        """Collect domain events from all saved aggregates."""
        ...

    async def publish_events(self) -> None:
        """Dispatch collected domain events via the message bus."""
        ...


# endregion CLASS_AbstractUnitOfWork
