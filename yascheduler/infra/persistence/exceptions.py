"""Adapter-layer exceptions for persistence operations."""
# region MODULE_CONTRACT
# PURPOSE: Signal persistence-layer contract violations (missing row, uninitialized UoW) with typed exceptions so callers distinguish programming errors from recoverable failures without depending on opaque pg8000 exceptions.
# SCOPE: Exception classes for UoW state-contract violations and repository row-existence precondition violations.
# KEYWORDS: persistence, exception, uow, task row not found, node row not found
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

from yascheduler.domain.exceptions import NodeRowNotFoundError

if TYPE_CHECKING:
    from yascheduler.domain.model import TaskId

__all__ = [
    "NodeRowNotFoundError",
    "TaskRowNotFoundError",
    "UnitOfWorkNotInitializedError",
]


class UnitOfWorkNotInitializedError(RuntimeError):
    """Raised when PostgresUnitOfWork methods are called without entering the async with context."""


# region CLASS_TaskRowNotFoundError
# PURPOSE: Signal a stale, missing, or status-guard-rejected task reference so callers can distinguish a programming error or lost-update from transient DB failures.
class TaskRowNotFoundError(RuntimeError):
    """Raised by PostgresTaskRepository.save/update_status when an UPDATE matches zero rows.

    Two causes, both surfacing as a zero-row UPDATE:
    - missing task_id (programming error / precondition violation), or
    - status guard rejection: ``save(task, expected_status=X)`` found the row
      no longer in status X (concurrent double-allocation / lost update).

    Callers SHALL NOT catch it for recovery logic.
    """

    def __init__(self, task_id: TaskId) -> None:
        """Record the task ID and format the error message."""
        self.task_id = task_id
        super().__init__(f"task row not found for task_id={task_id}")


# endregion CLASS_TaskRowNotFoundError
