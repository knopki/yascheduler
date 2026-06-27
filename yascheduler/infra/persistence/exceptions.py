# FILE: yascheduler/infra/persistence/exceptions.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Adapter-layer exceptions for persistence operations.
#   SCOPE: Exception classes for UoW state-contract violations and repository row-existence precondition violations.
#   DEPENDS: none
#   LINKS: M-PERSISTENCE-UOW, M-PERSISTENCE-POSTGRES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   UnitOfWorkNotInitializedError - raised when UoW API is used without entering context
#   TaskRowNotFoundError - raised by PostgresTaskRepository.save/update_status when an UPDATE targets a non-existent task_id
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Added TaskRowNotFoundError(RuntimeError) raised by PostgresTaskRepository.save/update_status on 0-row UPDATE outcome (fix-save-silent-zero-rows).
#   PREVIOUS_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY


class UnitOfWorkNotInitializedError(RuntimeError):
    """Raised when PostgresUnitOfWork methods are called without entering the async with context."""


# START_CONTRACT: TaskRowNotFoundError
#   PURPOSE: Signal that an UPDATE targeting a task_id affected 0 rows (the row does not exist).
#   INPUTS: { task_id: int - the task_id that was targeted but not found }
#   OUTPUTS: { None - no return value }
#   SIDE_EFFECTS: None — raises self; stores task_id on the instance
#   LINKS: M-PERSISTENCE-POSTGRES (PostgresTaskRepository.save/update_status)
# END_CONTRACT: TaskRowNotFoundError
class TaskRowNotFoundError(RuntimeError):
    """Raised by PostgresTaskRepository.save/update_status when an UPDATE targets a non-existent task_id.

    Programming-error / contract precondition violation: callers SHALL NOT catch it for
    recovery logic. Sibling of UnitOfWorkNotInitializedError.
    """

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        super().__init__(f"task row not found for task_id={task_id}")
