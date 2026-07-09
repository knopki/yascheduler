# FILE: yascheduler/domain/events.py
# VERSION: 1.4.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain events for task lifecycle transitions.
#   SCOPE: Lifecycle event types (DomainEvent base, TaskCreated, TaskAllocated, TaskCompleted, TaskFailed, TaskAbandoned) and the Event union.
#   DEPENDS: none
#   LINKS: M-DOMAIN-MODEL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   DomainEvent - Base frozen dataclass with task_id (TaskId), webhook_url, webhook_custom_params (all required)
#   TaskCreated - Task submitted event with engine_name
#   TaskAllocated - Task assigned to node with node_id (NodeId) and engine_name
#   TaskCompleted - Task finished with local_folder
#   TaskFailed - Task failed with reason
#   TaskAbandoned - Task abandoned on lost node with node_id (NodeId)
#   Event - Union type alias of all event types
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - Remove TaskCompleted.has_errors (unused; every complete path was a success, errors go through fail -> TaskFailed). Webhook wire format unaffected (webhook_handler does not read has_errors).
#   PREVIOUS_CHANGE: v1.3.0 - TaskAllocated and TaskAbandoned replace node_ip: str with node_id: NodeId (the node identity, not the transport address). NodeId imported under TYPE_CHECKING alongside TaskId.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .model import NodeId, TaskId


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
    node_id: NodeId
    engine_name: str


@dataclass(frozen=True)
class TaskCompleted(DomainEvent):
    local_folder: str


@dataclass(frozen=True)
class TaskFailed(DomainEvent):
    reason: str


@dataclass(frozen=True)
class TaskAbandoned(DomainEvent):
    node_id: NodeId


Event = Union[TaskCreated, TaskAllocated, TaskCompleted, TaskFailed, TaskAbandoned]
