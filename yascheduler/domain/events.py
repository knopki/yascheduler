# FILE: yascheduler/domain/events.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain events for task lifecycle transitions.
#   SCOPE: DomainEvent base, TaskCreated, TaskAllocated, TaskCompleted, TaskFailed, TaskAbandoned, Event union type.
#   DEPENDS: none
#   LINKS: M-DOMAIN-MODEL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   DomainEvent - Base frozen dataclass with task_id, webhook_url, webhook_custom_params
#   TaskCreated - Task submitted event with engine_name
#   TaskAllocated - Task assigned to node with node_ip and engine_name
#   TaskCompleted - Task finished with local_folder and has_errors
#   TaskFailed - Task failed with reason
#   TaskAbandoned - Task abandoned on lost node with node_ip
#   Event - Union type alias of all event types
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Create domain events for task lifecycle transitions.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    task_id: int
    webhook_url: str | None
    webhook_custom_params: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TaskCreated(DomainEvent):
    engine_name: str


@dataclass(frozen=True, kw_only=True)
class TaskAllocated(DomainEvent):
    node_ip: str
    engine_name: str


@dataclass(frozen=True, kw_only=True)
class TaskCompleted(DomainEvent):
    local_folder: str
    has_errors: bool


@dataclass(frozen=True, kw_only=True)
class TaskFailed(DomainEvent):
    reason: str


@dataclass(frozen=True, kw_only=True)
class TaskAbandoned(DomainEvent):
    node_ip: str


Event = TaskCreated | TaskAllocated | TaskCompleted | TaskFailed | TaskAbandoned
