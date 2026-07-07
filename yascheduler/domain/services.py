# FILE: yascheduler/domain/services.py
# VERSION: 1.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain services: cross-entity business logic for the scheduler domain.
#   SCOPE: Pure domain allocation service: match_task_to_node function for allocating tasks to compatible free machines.
#   DEPENDS: M-DOMAIN-MODEL
#   LINKS: M-DOMAIN-MODEL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   match_task_to_node - Select first compatible free machine for a task, or None
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - match_task_to_node as pure domain service.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import ConnectedMachine, Engine, Task


# START_CONTRACT: match_task_to_node
#   PURPOSE: Select first compatible free machine for a given task and engine.
#   INPUTS: { task: Task - The task to allocate | engine: Engine - Engine with platform requirements | free_machines: list[ConnectedMachine] - Candidate machines }
#   OUTPUTS: { ConnectedMachine | None - The first compatible machine, or None if none found }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: match_task_to_node
def match_task_to_node(
    task: Task,
    engine: Engine,
    free_machines: list[ConnectedMachine],
) -> ConnectedMachine | None:
    """Return the first compatible free machine for a task, or None if none found."""
    # START_BLOCK_MATCH_MACHINES
    for machine in free_machines:
        if machine.is_compatible(engine.platforms):
            return machine
    return None
    # END_BLOCK_MATCH_MACHINES
