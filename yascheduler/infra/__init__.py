# FILE: yascheduler/infra/__init__.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Adapters layer facade — sole public surface for cross-layer consumers (application, composition root).
#   SCOPE: Re-exports SSHMachineRepository, SSHMachineOperations, retry exceptions, cloud provisioner + adapter protocol, schema initializer, webhook handler, Postgres UoW.
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
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Re-export SSHMachineRepository + SSHMachineOperations instead of SSHMachineGateway (decompose-ssh-gateway). The god-class split into collection (repository) + operations; composition root and consumers now take two ports.
#   PREVIOUS_CHANGE: v1.2.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY

from .cloud import CloudAdapter, CloudProvisionerImpl, resolve_adapter
from .notifier import webhook_handler
from .persistence import PostgresUnitOfWork, apply_schema
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
    "apply_schema",
    "list_private_keys",
]
