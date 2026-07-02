# FILE: yascheduler/domain/events.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain events for task lifecycle transitions.
#   SCOPE: DomainEvent base, TaskCreated, TaskAllocated, TaskCompleted, TaskFailed, TaskAbandoned, Event union type.
#   DEPENDS: none
#   LINKS: M-DOMAIN-MODEL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   DomainEvent - Base frozen dataclass with task_id (TaskId), webhook_url, webhook_custom_params (all required)
#   TaskCreated - Task submitted event with engine_name
#   TaskAllocated - Task assigned to node with node_ip and engine_name
#   TaskCompleted - Task finished with local_folder and has_errors
#   TaskFailed - Task failed with reason
#   TaskAbandoned - Task abandoned on lost node with node_ip
#   Event - Union type alias of all event types
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - DomainEvent.task_id: int -> TaskId (add-task-id-identity); the 5 subclasses inherit the new type. TaskId imported under TYPE_CHECKING (annotations are strings via from __future__ import annotations). Python 3.9 compat preserved: typing.Union for the Event alias, no PEP 604.
#   PREVIOUS_CHANGE: v1.1.0 - Restore Python 3.9 compatibility: drop dataclass kw_only (3.10+), make webhook_custom_params required (avoids non-default-after-default inheritance error), use typing.Union instead of PEP 604 X|Y at runtime.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .model import TaskId


@dataclass(frozen=True)
class DomainEvent:
    task_id: TaskId
    webhook_url: str | None
    webhook_custom_params: dict[str, object]


@dataclass(frozen=True)
class TaskCreated(DomainEvent):
    engine_name: str


@dataclass(frozen=True)
class TaskAllocated(DomainEvent):
    node_ip: str
    engine_name: str


@dataclass(frozen=True)
class TaskCompleted(DomainEvent):
    local_folder: str
    has_errors: bool


@dataclass(frozen=True)
class TaskFailed(DomainEvent):
    reason: str


@dataclass(frozen=True)
class TaskAbandoned(DomainEvent):
    node_ip: str


Event = Union[TaskCreated, TaskAllocated, TaskCompleted, TaskFailed, TaskAbandoned]
