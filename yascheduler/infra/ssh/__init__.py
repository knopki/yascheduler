# FILE: yascheduler/infra/ssh/__init__.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: SSH adapter package root — re-exports repository, operations, and retry exceptions.
#   SCOPE: Package marker; public re-exports of MachineRepository, SSHMachineRepository, SSHMachineOperations, AllSSHRetryExc, SFTPRetryExc.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-EXCEPTIONS
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-SSH-EXCEPTIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   MachineRepository - Domain Protocol for the connected-machine collection (re-exported from .repository)
#   SSHMachineRepository - Concrete MachineRepository implementation
#   SSHMachineOperations - Concrete MachineOperations implementation (composes TaskDeployer/OutputDownloader/OccupancyChecker)
#   AllSSHRetryExc - Union of all retryable SSH exceptions
#   SFTPRetryExc - Tuple of retriable SFTP exception types
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Re-export MachineRepository (Protocol), SSHMachineRepository, SSHMachineOperations (decompose-ssh-gateway). SSHMachineGateway removed (god-class dissolved into repository + operations). _MachineState NOT re-exported (private to repository.py; tests import via yascheduler.infra.ssh.repository._MachineState).
#   PREVIOUS_CHANGE: v1.1.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
# END_CHANGE_SUMMARY

from yascheduler.domain import MachineRepository

from .exceptions import AllSSHRetryExc, SFTPRetryExc
from .operations import SSHMachineOperations
from .repository import SSHMachineRepository

__all__ = [
    "AllSSHRetryExc",
    "MachineRepository",
    "SFTPRetryExc",
    "SSHMachineOperations",
    "SSHMachineRepository",
]
