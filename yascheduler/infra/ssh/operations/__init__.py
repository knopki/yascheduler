# FILE: yascheduler/infra/ssh/operations/__init__.py
# VERSION: 2.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Single-machine SSH operations collaborators — stateless deploy/download/occupancy classes that take a session per call.
#   SCOPE: Re-exports TaskDeployer, OutputDownloader, OccupancyChecker (the concrete collaborator classes consumers type against).
#   DEPENDS: M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY
#   LINKS: M-SSH-OPERATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskDeployer - Upload inputs and spawn calculation process (re-exported from .deployment)
#   OutputDownloader - Per-file SFTP-isolated download with retry and error classification (re-exported from .download)
#   OccupancyChecker - pgrep/cmd-based occupancy check + monitor installer (re-exported from .occupancy)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Dissolve the SSHMachineOperations facade. The package now exports the three collaborators directly; consumers (orchestrator, use cases, di) construct and type against them.
#   PREVIOUS_CHANGE: v1.0.0 - Initial package created. Extracted operations responsibility from the dissolved SSHMachineGateway god-class; composes three sibling collaborators (TaskDeployer, OutputDownloader, OccupancyChecker) via composition, not inheritance.
# END_CHANGE_SUMMARY

from .deployment import TaskDeployer
from .download import OutputDownloader
from .occupancy import OccupancyChecker

__all__ = [
    "TaskDeployer",
    "OutputDownloader",
    "OccupancyChecker",
]
