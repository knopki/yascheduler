# FILE: yascheduler/application/__init__.py
# VERSION: 1.5.0
# START_MODULE_CONTRACT
#   PURPOSE: Application layer facade — sole public surface for cross-layer consumers and composition root.
#   SCOPE: Re-export AbstractUnitOfWork, Orchestrator, MessageBus, submit_task, query_tasks, abandon_node, AllocationTracker.
#   DEPENDS: M-APPLICATION-UOW, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-MESSAGE-BUS, M-APPLICATION-SUBMIT, M-APPLICATION-QUERY-TASKS, M-APPLICATION-ALLOCATION-TRACKER, M-APPLICATION-ABANDON-NODE
#   LINKS: M-APPLICATION-UOW, M-APPLICATION-SUBMIT, M-APPLICATION-QUERY-TASKS, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-MESSAGE-BUS, M-DI, M-APPLICATION-ALLOCATION-TRACKER, M-APPLICATION-ABANDON-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AbstractUnitOfWork - Protocol for transactional persistence boundaries
#   Orchestrator - Daemon loop manager: allocate, consume, deallocate
#   MessageBus - In-process event dispatcher with handler registry
#   submit_task - Use case: register a new task in TO_DO state
#   query_tasks - Use case: read-only task query by statuses or job IDs
#   abandon_node - Use case: clean up never-connected cloud node + release stuck TO_DO task
#   AllocationTracker - In-memory dedup of in-flight cloud allocations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.5.0 - Re-export abandon_node use case (fix-never-connected-node-leak).
#   PREVIOUS_CHANGE: v1.4.0 - Re-export query_tasks use case (client-query-uow).
# END_CHANGE_SUMMARY

from .abandon_node import abandon_node
from .allocation_tracker import AllocationTracker
from .message_bus import MessageBus
from .orchestrator import Orchestrator
from .query_tasks import query_tasks
from .submit_task import submit_task
from .uow import AbstractUnitOfWork

__all__ = [
    "AbstractUnitOfWork",
    "AllocationTracker",
    "MessageBus",
    "Orchestrator",
    "abandon_node",
    "query_tasks",
    "submit_task",
]
