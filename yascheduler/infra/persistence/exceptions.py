"""Adapter-layer exceptions for persistence operations."""
# region MODULE_CONTRACT
# PURPOSE: Signal persistence-layer contract violations (missing row, uninitialized UoW) with typed exceptions so callers distinguish programming errors from recoverable failures without depending on opaque pg8000 exceptions.
# SCOPE: Exception classes for UoW state-contract violations and repository row-existence precondition violations.
# KEYWORDS: persistence, exception, uow, task row not found
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yascheduler.domain.model import TaskId

__all__ = ["TaskRowNotFoundError", "UnitOfWorkNotInitializedError"]


class UnitOfWorkNotInitializedError(RuntimeError):
    """Raised when PostgresUnitOfWork methods are called without entering the async with context."""


# region CLASS_TaskRowNotFoundError
# PURPOSE: Signal a stale or missing task reference so callers can distinguish a programming error (expected row absent) from transient DB failures.
class TaskRowNotFoundError(RuntimeError):
    """Raised by PostgresTaskRepository.save/update_status when an UPDATE targets a non-existent task_id.

    Programming-error / contract precondition violation: callers SHALL NOT catch it for
    recovery logic. Sibling of UnitOfWorkNotInitializedError.
    """

    def __init__(self, task_id: TaskId) -> None:
        """Record the task ID and format the error message."""
        self.task_id = task_id
        super().__init__(f"task row not found for task_id={task_id}")


# endregion CLASS_TaskRowNotFoundError
