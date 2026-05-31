# FILE: yascheduler/adapters/persistence/exceptions.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Adapter-layer exceptions for persistence operations.
#   SCOPE: Exception classes for UoW state-contract violations.
#   DEPENDS: none
#   LINKS: M-PERSISTENCE-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   UnitOfWorkNotInitializedError - raised when UoW API is used without entering context
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial creation with UnitOfWorkNotInitializedError.
# END_CHANGE_SUMMARY


class UnitOfWorkNotInitializedError(RuntimeError):
    """Raised when PostgresUnitOfWork methods are called without entering the async with context."""
