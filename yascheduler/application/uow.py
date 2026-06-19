# FILE: yascheduler/application/uow.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Abstract Unit of Work Protocol defining the transactional boundary contract for use cases.
#   SCOPE: AbstractUnitOfWork Protocol with tasks, nodes, commit, rollback, event dispatch, and async context manager support.
#   DEPENDS: M-DOMAIN-PORTS, M-DOMAIN-EVENTS
#   LINKS: M-DOMAIN-PORTS, M-PERSISTENCE-UOW, M-DOMAIN-EVENTS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AbstractUnitOfWork - Protocol for transactional boundaries with task and node repositories
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Add collect_events and publish_events to AbstractUnitOfWork Protocol.
#   PREVIOUS_CHANGE: v1.0.0 - Create AbstractUnitOfWork Protocol for application layer.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import types

    from yascheduler.domain.events import DomainEvent
    from yascheduler.domain.ports import NodeRepository, TaskRepository


@runtime_checkable
class AbstractUnitOfWork(Protocol):
    """Async context manager providing task and node repositories sharing a transaction."""

    @property
    def tasks(self) -> TaskRepository: ...

    @property
    def nodes(self) -> NodeRepository: ...

    async def __aenter__(self) -> AbstractUnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def collect_events(self) -> list[DomainEvent]: ...

    async def publish_events(self) -> None: ...
