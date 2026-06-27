# FILE: yascheduler/infra/ssh/operations/__init__.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: SSH operations on a single machine — command exec, SFTP, process inspection, node setup, task deployment, output download, occupancy check.
#   SCOPE: Re-exports SSHMachineOperations and collaborator classes (TaskDeployer, OutputDownloader, OccupancyChecker).
#   DEPENDS: M-SSH-OPERATIONS-BASE, M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY
#   LINKS: M-SSH-OPERATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SSHMachineOperations - Operations on a single machine; composes deploy/download/occupancy collaborators
#   TaskDeployer - Upload inputs and spawn calculation process (re-exported from .deployment)
#   OutputDownloader - Per-file SFTP-isolated download with retry and error classification (re-exported from .download)
#   OccupancyChecker - pgrep/cmd-based occupancy check + monitor installer (re-exported from .occupancy)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial package created (decompose-ssh-gateway). Extracted operations responsibility from the dissolved SSHMachineGateway god-class; composes three sibling collaborators (TaskDeployer, OutputDownloader, OccupancyChecker) via composition, not inheritance.
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from .base import SSHMachineOperations

__all__ = [
    "SSHMachineOperations",
]
