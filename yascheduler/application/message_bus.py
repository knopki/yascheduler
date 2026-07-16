"""In-process message bus that dispatches domain events to registered handlers."""
# region MODULE_CONTRACT
# PURPOSE: Decouple event emitters from handlers by routing DomainEvent instances to registered callbacks in-process.
# SCOPE: MessageBus class — type-based handler registry and async dispatch loop with per-handler error isolation.
# KEYWORDS: message bus, event bus, domain events, dispatch, handler
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import DomainEvent

logger = logging.getLogger(__name__)

__all__ = ["MessageBus"]


# region CLASS_MessageBus
# PURPOSE: Route domain events to registered handlers with per-handler error isolation so one failing handler does not block others.
class MessageBus:
    """In-process event dispatcher with type-based handler registry."""

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Callable[[DomainEvent], Any]]] = {}

    # region METHOD_register
    # PURPOSE: Subscribe a handler to an event type so dispatch() can invoke it when events of that type are published.
    def register(self, event_type: type, handler: Callable) -> None:
        """Register a handler callable for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    # endregion METHOD_register

    # region METHOD_dispatch
    # PURPOSE: Dispatch a sequence of domain events to their registered handlers, catching and logging per-handler failures.
    async def dispatch(self, events: Sequence[DomainEvent]) -> None:
        """Dispatch a sequence of domain events to their registered handlers."""
        for event in events:
            for handler in self._handlers.get(type(event), []):
                try:
                    result = handler(event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:  # noqa: PERF203
                    logger.exception(
                        "message bus handler %s failed for %s",
                        getattr(handler, "__name__", handler),
                        type(event).__name__,
                    )

    # endregion METHOD_dispatch


# endregion CLASS_MessageBus
