"""SSH adapter package root — re-exports repository, session, operations collaborators, and retry exceptions."""
# FILE: yascheduler/infra/ssh/__init__.py
# VERSION: 1.4.0
# START_MODULE_CONTRACT
#   PURPOSE: SSH adapter package root — re-exports repository, session, operations collaborators, and retry exceptions.
#   SCOPE: SSH subpackage facade: connected-machine repository, single-machine operations collaborators, retry exception aliases.
#   DEPENDS: M-PLATFORM-PROTOCOL, M-SSH-REPOSITORY, M-SSH-SESSION, M-SSH-OPERATIONS
#   LINKS: M-PLATFORM-PROTOCOL, M-SSH-REPOSITORY, M-SSH-SESSION, M-SSH-OPERATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   MachineRepository - Domain Protocol for the connected-machine collection (re-exported from .repository)
#   SSHMachineRepository - Concrete MachineRepository implementation
#   SSHMachineSession - Concrete MachineSession implementation (connected-machine entity handle)
#   TaskDeployer - Stateless collaborator: upload inputs and spawn calculation (re-exported from .operations)
#   OutputDownloader - Stateless collaborator: per-file SFTP-isolated download with retry (re-exported from .operations)
#   OccupancyChecker - Stateless collaborator: pgrep/cmd-based occupancy check + monitor installer (re-exported from .operations)
#   AllSSHRetryExc - Union of all retryable SSH exceptions
#   SFTPRetryExc - Tuple of retriable SFTP exception types
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - Drop SSHMachineOperations re-export (facade dissolved); re-export TaskDeployer, OutputDownloader, OccupancyChecker directly.
#   PREVIOUS_CHANGE: v1.3.0 - Re-export SSHMachineSession. Joined __all__ and explicit import next to SSHMachineRepository.
# END_CHANGE_SUMMARY

from yascheduler.domain import MachineRepository

from .operations import OccupancyChecker, OutputDownloader, TaskDeployer
from .platform.protocol import AllSSHRetryExc, SFTPRetryExc
from .repository import SSHMachineRepository
from .session import SSHMachineSession

__all__ = [
    "AllSSHRetryExc",
    "MachineRepository",
    "OccupancyChecker",
    "OutputDownloader",
    "SFTPRetryExc",
    "SSHMachineRepository",
    "SSHMachineSession",
    "TaskDeployer",
]
