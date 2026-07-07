# FILE: yascheduler/infra/ssh/__init__.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: SSH adapter package root — re-exports repository, session, operations, and retry exceptions.
#   SCOPE: SSH subpackage facade: connected-machine repository, operations facade, retry exception aliases.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-SESSION, M-SSH-OPERATIONS, M-SSH-EXCEPTIONS
#   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION, M-SSH-OPERATIONS, M-SSH-EXCEPTIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   MachineRepository - Domain Protocol for the connected-machine collection (re-exported from .repository)
#   SSHMachineRepository - Concrete MachineRepository implementation
#   SSHMachineSession - Concrete MachineSession implementation (connected-machine entity handle)
#   SSHMachineOperations - Concrete MachineOperations implementation (facade; composes TaskDeployer/OutputDownloader/OccupancyChecker)
#   AllSSHRetryExc - Union of all retryable SSH exceptions
#   SFTPRetryExc - Tuple of retriable SFTP exception types
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Re-export SSHMachineSession. Joined __all__ and explicit import next to SSHMachineRepository.
#   PREVIOUS_CHANGE: v1.2.0 - Re-export MachineRepository (Protocol), SSHMachineRepository, SSHMachineOperations. SSHMachineGateway removed (god-class dissolved into repository + operations). _MachineState NOT re-exported (private to repository.py).
# END_CHANGE_SUMMARY

from yascheduler.domain import MachineRepository

from .exceptions import AllSSHRetryExc, SFTPRetryExc
from .operations import SSHMachineOperations
from .repository import SSHMachineRepository
from .session import SSHMachineSession

__all__ = [
    "AllSSHRetryExc",
    "MachineRepository",
    "SFTPRetryExc",
    "SSHMachineOperations",
    "SSHMachineRepository",
    "SSHMachineSession",
]
