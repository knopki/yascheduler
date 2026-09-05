"""SSH adapter package root — re-exports repository, session, operations collaborators, and retry exceptions."""
# region MODULE_CONTRACT
# PURPOSE: SSH subpackage facade — re-export connected-machine repository, session, operations collaborators, and retry exception aliases.
# SCOPE:
# - MachineRepository protocol (re-exported from domain)
# - SSHMachineRepository, SSHMachineSession, TaskDeployer, OutputDownloader, OccupancyChecker
# - AllSSHRetryExc, SFTPRetryExc retry exception aliases
# KEYWORDS: ssh, facade, re-export, repository, session, operations
# endregion MODULE_CONTRACT

from yascheduler.domain import MachineRepository

from .operations import OccupancyChecker, OutputDownloader, TaskDeployer
from .platform.types import AllSSHRetryExc, SFTPRetryExc
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
