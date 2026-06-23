# FILE: yascheduler/infra/__init__.py
# VERSION: 1.2.1
# START_MODULE_CONTRACT
#   PURPOSE: Adapters layer facade — sole public surface for cross-layer consumers (application, composition root).
#   SCOPE: Re-exports gateway, retry exceptions, cloud provisioner + adapter protocol, schema initializer, webhook handler, Postgres UoW.
#   DEPENDS: M-SSH, M-CLOUD, M-PERSISTENCE, M-NOTIFIER
#   LINKS: M-SSH, M-CLOUD, M-PERSISTENCE, M-NOTIFIER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SSHMachineGateway - Async SSH machine gateway implementation
#   AllSSHRetryExc - Tuple of all retryable SSH exceptions
#   SFTPRetryExc - Tuple of retryable SFTP exceptions
#   CloudProvisionerImpl - Cloud provisioner implementation
#   CloudAdapter - Frozen attrs class wrapping create/delete callables + platform checks
#   webhook_handler - Async webhook event handler
#   PostgresUnitOfWork - Concrete UoW backed by Postgres (composition root wiring)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.2.0 - Re-export CloudAdapter and PostgresUnitOfWork for composition root wiring (clean-architecture-imports R2).
# END_CHANGE_SUMMARY

from .cloud import CloudAdapter, CloudProvisionerImpl
from .notifier import webhook_handler
from .persistence import PostgresUnitOfWork
from .ssh import AllSSHRetryExc, SFTPRetryExc, SSHMachineGateway

__all__ = [
    "AllSSHRetryExc",
    "CloudAdapter",
    "CloudProvisionerImpl",
    "PostgresUnitOfWork",
    "SSHMachineGateway",
    "SFTPRetryExc",
    "webhook_handler",
]
