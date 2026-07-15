"""Adapters layer facade — sole public surface for cross-layer consumers (application, composition root)."""
# FILE: yascheduler/infra/__init__.py
# VERSION: 1.5.0
# START_MODULE_CONTRACT
#   PURPOSE: Adapters layer facade — sole public surface for cross-layer consumers (application, composition root).
#   SCOPE: Re-exports from infra subpackages for cross-layer consumers.
#   DEPENDS: M-SSH, M-CLOUD, M-PERSISTENCE, M-NOTIFIER
#   LINKS: M-SSH, M-CLOUD, M-PERSISTENCE, M-NOTIFIER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SSHMachineRepository - Concrete MachineRepository implementation (connected-machine collection)
#   TaskDeployer - Stateless collaborator: upload inputs and spawn calculation process
#   OutputDownloader - Stateless collaborator: per-file SFTP-isolated download with retry and error classification
#   OccupancyChecker - Stateless collaborator: pgrep/cmd-based occupancy check + monitor installer
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
#   LAST_CHANGE: v1.5.0 - Drop SSHMachineOperations re-export (facade dissolved); re-export the three collaborators (TaskDeployer/OutputDownloader/OccupancyChecker) consumers now type against.
#   PREVIOUS_CHANGE: v1.4.0 - Re-export apply_migrations alongside apply_schema (add-db-migrations); yainit and test fixtures call it after apply_schema.
# END_CHANGE_SUMMARY

from .cloud import CloudAdapter, CloudProvisionerImpl, resolve_adapter
from .notifier import webhook_handler
from .persistence import PostgresUnitOfWork, apply_migrations, apply_schema
from .ssh import (
    AllSSHRetryExc,
    OccupancyChecker,
    OutputDownloader,
    SFTPRetryExc,
    SSHMachineRepository,
    TaskDeployer,
)
from .ssh.keys import list_private_keys

__all__ = [
    "AllSSHRetryExc",
    "CloudAdapter",
    "CloudProvisionerImpl",
    "OccupancyChecker",
    "OutputDownloader",
    "PostgresUnitOfWork",
    "SFTPRetryExc",
    "SSHMachineRepository",
    "TaskDeployer",
    "apply_migrations",
    "apply_schema",
    "list_private_keys",
    "resolve_adapter",
    "webhook_handler",
]
