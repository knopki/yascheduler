# FILE: yascheduler/application/message_bus.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: In-process message bus that dispatches domain events to registered handlers.
#   SCOPE: MessageBus class — in-process event dispatch with type-based handler registry.
#   DEPENDS: M-DOMAIN-EVENTS
#   LINKS: M-DOMAIN-EVENTS, M-APPLICATION-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   MessageBus - Event dispatcher with type-based handler registry
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Create MessageBus for domain event dispatch.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from yascheduler.domain import DomainEvent

logger = logging.getLogger(__name__)


# START_CONTRACT: MessageBus
#   PURPOSE: In-process event dispatcher with type-based handler registry.
#   INPUTS: { None - no constructor parameters }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Handler invocation via dispatch.
#   LINKS: M-DOMAIN-EVENTS
# END_CONTRACT: MessageBus
class MessageBus:
    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Callable[[DomainEvent], Any]]] = {}

    # START_CONTRACT: MessageBus.register
    #   PURPOSE: Register a handler callable for a specific event type.
    #   INPUTS: { event_type: type, handler: Callable }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None — in-memory only.
    #   LINKS: M-DOMAIN-EVENTS
    # END_CONTRACT: MessageBus.register
    def register(self, event_type: type, handler: Callable) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    # START_CONTRACT: MessageBus.dispatch
    #   PURPOSE: Dispatch a sequence of domain events to their registered handlers.
    #   INPUTS: { events: Sequence[DomainEvent] }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Invokes registered handlers (their own side effects).
    #   LINKS: M-DOMAIN-EVENTS
    # END_CONTRACT: MessageBus.dispatch
    async def dispatch(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            for handler in self._handlers.get(type(event), []):
                try:
                    result = handler(event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception(
                        "[MessageBus][dispatch] Handler %s failed for %s",
                        getattr(handler, "__name__", handler),
                        type(event).__name__,
                    )
