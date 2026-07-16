"""Domain events for task lifecycle transitions."""
# region MODULE_CONTRACT
# PURPOSE: Record task lifecycle transitions as immutable values so the UoW can dispatch webhooks/handlers without re-querying aggregates.
# SCOPE:
# - DomainEvent base + TaskCreated, TaskAllocated, TaskCompleted, TaskFailed, TaskAbandoned, and the Event union alias.
# - NOT: event dispatch (application.message_bus) or webhook wire format (infra.notifier).
# INVARIANTS: Every event is frozen; task_id is always present.
# KEYWORDS: domain event, lifecycle, webhook, TaskCreated, TaskAllocated, TaskCompleted, TaskFailed, TaskAbandoned
# endregion MODULE_CONTRACT

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .model import NodeId, TaskId

__all__ = [
    "DomainEvent",
    "Event",
    "TaskAbandoned",
    "TaskAllocated",
    "TaskCompleted",
    "TaskCreated",
    "TaskFailed",
]


@dataclass(frozen=True)
class DomainEvent:
    """Domainevent."""

    task_id: TaskId
    webhook_url: str | None
    webhook_custom_params: dict[str, object]


@dataclass(frozen=True)
class TaskCreated(DomainEvent):
    """Taskcreated."""

    engine_name: str


@dataclass(frozen=True)
class TaskAllocated(DomainEvent):
    """Taskallocated."""

    node_id: NodeId
    engine_name: str


@dataclass(frozen=True)
class TaskCompleted(DomainEvent):
    """Taskcompleted."""

    local_folder: str


@dataclass(frozen=True)
class TaskFailed(DomainEvent):
    """Taskfailed."""

    reason: str


@dataclass(frozen=True)
class TaskAbandoned(DomainEvent):
    """Taskabandoned."""

    node_id: NodeId


Event = Union[TaskCreated, TaskAllocated, TaskCompleted, TaskFailed, TaskAbandoned]
