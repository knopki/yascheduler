"""Domain services: cross-entity business logic for the scheduler domain."""
# region MODULE_CONTRACT
# PURPOSE: Decide which free machine runs a task based on engine-platform compatibility, keeping allocation logic testable and free of persistence/transport concerns.
# SCOPE:
# - match_task_to_node — pick the first machine whose platform matches the engine.
# - NOT: persistence, SSH, cloud provisioning, or scheduling/capacity policy.
# INVARIANTS: Inputs are never mutated; the decision considers only engine-platform compatibility.
# RATIONALE:
# - Q: Why is the first parameter `_task` and unused?
#   A: The signature reserves room for task-aware allocation (e.g. CPU/core requirements) without changing call sites; current matching keys only on the engine.
# KEYWORDS: allocation, matching, free machine, platform compatibility
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import ConnectedMachine, Engine, Task

__all__ = ["match_task_to_node"]


# region FUNC_match_task_to_node
# PURPOSE: Select the first compatible free machine for a task, so the allocator has a deterministic candidate selector.
# ENSURES: The result, when not None, satisfies machine.is_compatible(engine.platforms).
def match_task_to_node(
    _task: Task,
    engine: Engine,
    free_machines: list[ConnectedMachine],
) -> ConnectedMachine | None:
    """Return the first compatible free machine for a task, or None if none found."""
    for machine in free_machines:
        if machine.is_compatible(engine.platforms):
            return machine
    return None


# endregion FUNC_match_task_to_node
