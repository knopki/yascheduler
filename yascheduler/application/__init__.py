# FILE: yascheduler/application/__init__.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Application layer facade — sole public surface for cross-layer consumers and composition root.
#   SCOPE: Re-export AbstractUnitOfWork, Orchestrator, MessageBus, submit_task.
#   DEPENDS: M-APPLICATION-UOW, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-MESSAGE-BUS, M-APPLICATION-SUBMIT, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-UOW, M-APPLICATION-SUBMIT, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-MESSAGE-BUS, M-DI, M-APPLICATION-ALLOCATION-TRACKER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AbstractUnitOfWork - Protocol for transactional persistence boundaries
#   Orchestrator - Daemon loop manager: allocate, consume, deallocate
#   MessageBus - In-process event dispatcher with handler registry
#   submit_task - Use case: register a new task in TO_DO state
#   AllocationTracker - In-memory dedup of in-flight cloud allocations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Re-export AllocationTracker (cloud-provisioner-pure).
#   PREVIOUS_CHANGE: v1.2.0 - Re-export submit_task for composition root wiring (clean-architecture-imports R2).
# END_CHANGE_SUMMARY

from .allocation_tracker import AllocationTracker
from .message_bus import MessageBus
from .orchestrator import Orchestrator
from .submit_task import submit_task
from .uow import AbstractUnitOfWork

__all__ = [
    "AbstractUnitOfWork",
    "AllocationTracker",
    "MessageBus",
    "Orchestrator",
    "submit_task",
]
