# FILE: yascheduler/infra/__init__.py
# VERSION: 1.4.0
# START_MODULE_CONTRACT
#   PURPOSE: Adapters layer facade — sole public surface for cross-layer consumers (application, composition root).
#   SCOPE: Re-exports from infra subpackages for cross-layer consumers.
#   DEPENDS: M-SSH, M-CLOUD, M-PERSISTENCE, M-NOTIFIER
#   LINKS: M-SSH, M-CLOUD, M-PERSISTENCE, M-NOTIFIER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SSHMachineRepository - Concrete MachineRepository implementation (connected-machine collection)
#   SSHMachineOperations - Concrete MachineOperations implementation (single-machine operations)
#   AllSSHRetryExc - Tuple of all retryable SSH exceptions
#   SFTPRetryExc - Tuple of retryable SFTP exceptions
#   CloudProvisionerImpl - Cloud provisioner implementation
#   CloudAdapter - Frozen attrs class wrapping create/delete callables + platform checks
#   webhook_handler - Async webhook event handler
#   PostgresUnitOfWork - Concrete UoW backed by Postgres (composition root wiring)
#   apply_schema - Apply schema.sql in a transactional block (yainit / test fixtures)
#   apply_migrations - Apply pending .sql/.py migrations from sql/migrations/ (yainit / test fixtures)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - Re-export apply_migrations alongside apply_schema (add-db-migrations); yainit and test fixtures call it after apply_schema.
#   PREVIOUS_CHANGE: v1.3.0 - Re-export SSHMachineRepository + SSHMachineOperations.
# END_CHANGE_SUMMARY

from .cloud import CloudAdapter, CloudProvisionerImpl, resolve_adapter
from .notifier import webhook_handler
from .persistence import PostgresUnitOfWork, apply_migrations, apply_schema
from .ssh import (
    AllSSHRetryExc,
    SFTPRetryExc,
    SSHMachineOperations,
    SSHMachineRepository,
)
from .ssh.keys import list_private_keys

__all__ = [
    "AllSSHRetryExc",
    "CloudAdapter",
    "CloudProvisionerImpl",
    "PostgresUnitOfWork",
    "SSHMachineOperations",
    "SSHMachineRepository",
    "SFTPRetryExc",
    "webhook_handler",
    "resolve_adapter",
    "apply_migrations",
    "apply_schema",
    "list_private_keys",
]
