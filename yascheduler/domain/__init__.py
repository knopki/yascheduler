# FILE: yascheduler/domain/__init__.py
# VERSION: 1.7.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain layer entry point — re-exports domain events for public API.
#   SCOPE: Re-exports DomainEvent types and Event union from .events.
#   DEPENDS: M-DOMAIN-EVENTS
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   DomainEvent - Base frozen dataclass for all task lifecycle events
#   TaskCreated - Task submitted event
#   TaskAllocated - Task assigned to node event
#   TaskCompleted - Task finished event
#   TaskFailed - Task failed event
#   TaskAbandoned - Task abandoned on lost node event
#   Event - Union type alias of all event types
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Add domain event re-exports for public API (domain-events change).
#   PREVIOUS_CHANGE: v1.6.0 - Create domain layer scaffold as part of Hexagonal + DDD migration.
# END_CHANGE_SUMMARY

__all__ = [
    "DomainEvent",
    "Event",
    "TaskAbandoned",
    "TaskAllocated",
    "TaskCompleted",
    "TaskCreated",
    "TaskFailed",
]

from .events import (
    DomainEvent,
    Event,
    TaskAbandoned,
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)
