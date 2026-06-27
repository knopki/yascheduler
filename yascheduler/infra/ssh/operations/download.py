# FILE: yascheduler/infra/ssh/operations/download.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: OutputDownloader — per-file SFTP-isolated download with retry, error classification, conservative post-loop rmtree.
#   SCOPE: OutputDownloader class + my_backoff_sftp partial (canonical location — its first user is download_outputs).
#   DEPENDS: M-SSH-OPERATIONS-BASE, M-SSH-REPOSITORY, M-SSH-EXCEPTIONS, M-PLATFORM
#   LINKS: M-SSH-OPS-DOWNLOAD
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   my_backoff_sftp - Partial backoff decorator for SFTPRetryExc (canonical; first user is download_outputs)
#   OutputDownloader - Per-file SFTP-isolated download with retry and error classification; 3-tuple return
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial module created (decompose-ssh-gateway). Extracted from the dissolved SSHMachineGateway god-class; download_outputs moved verbatim with self.get_sftp → self._operations.get_sftp, self.get_path → self._repository.get_path. my_backoff_sftp defined here (canonical location per design D4 note).
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

import backoff
from asyncssh.sftp import SFTPError

from ..exceptions import SFTPRetryExc

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from ..repository import SSHMachineRepository
    from .base import SSHMachineOperations

my_backoff_sftp = partial(
    backoff.on_exception,
    wait_gen=backoff.fibo,
    max_time=60,
    exception=SFTPRetryExc,
)


# START_CONTRACT: OutputDownloader
#   PURPOSE: Per-file SFTP-isolated download with retry, error classification, conservative post-loop rmtree.
#   LINKS: M-SSH-OPS-DOWNLOAD, M-SSH-OPERATIONS, M-SSH-REPOSITORY
# END_CONTRACT: OutputDownloader
class OutputDownloader:
    """Per-file SFTP-isolated download with retry and error classification.

    Opens a FRESH SFTP client per file (dead-connection blast radius bounded
    to one file). Classifies per-file exceptions into transient (SFTPRetryExc)
    or permanent (everything else). Removes the remote dir tree ONCE only on
    full success (both error lists empty). Session-level failures are caught
    and recorded as transient. Returns a 3-tuple
    (meta_add, transient_errors, permanent_errors).
    """

    def __init__(
        self,
        operations: SSHMachineOperations,
        repository: SSHMachineRepository,
        log: logging.Logger,
    ) -> None:
        self._operations = operations
        self._repository = repository
        self._log = log

    # START_CONTRACT: OutputDownloader.download_outputs
    #   PURPOSE: Per-file SFTP-isolated download with retry, error classification, conservative post-loop rmtree.
    #   INPUTS: { ip: str, remote_dir: str, local_dir: Path, files: list[str], task_id: int | None }
    #   OUTPUTS: { tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]] - (meta_add, transient_errors, permanent_errors) }
    #   SIDE_EFFECTS: Downloads files via SFTP using a FRESH client per file; removes the remote directory tree ONCE after the loop ONLY when both transient_errors and permanent_errors are empty.
    #   LINKS: M-SSH-OPS-DOWNLOAD, M-SSH-OPERATIONS, M-SSH-REPOSITORY
    # END_CONTRACT: OutputDownloader.download_outputs
    async def download_outputs(
        self,
        ip: str,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: int | None = None,
    ) -> tuple[
        list[tuple[str, Any]],
        list[tuple[str | None, Exception]],
        list[tuple[str | None, Exception]],
    ]:
        # START_BLOCK_DOWNLOAD_OUTPUTS
        meta_add: list[tuple[str, Any]] = [
            ("remote_folder", remote_dir),
            ("local_folder", str(local_dir)),
        ]
        transient_errors: list[tuple[str | None, Exception]] = []
        permanent_errors: list[tuple[str | None, Exception]] = []
        path_type = self._repository.get_path(ip)
        file_get_retry = my_backoff_sftp()

        try:
            # START_BLOCK_PER_FILE_DOWNLOAD
            # Fresh SFTP client per file: a dropped channel on file N invalidates only N's
            # retries. The inner try classifies ONLY sftp.get failures — a get_sftp OPEN
            # failure escapes to the outer handler as a session-level transient (not per-file).
            for out_file in files:
                async with self._operations.get_sftp(ip) as sftp:
                    try:
                        await file_get_retry(sftp.get)(
                            out_file, local_dir, preserve=True
                        )
                    except (OSError, SFTPError) as err:
                        # START_BLOCK_CLASSIFY
                        if isinstance(err, SFTPRetryExc):
                            transient_errors.append((out_file, err))
                        else:
                            permanent_errors.append((out_file, err))
                        # END_BLOCK_CLASSIFY
                        self._log.warning(
                            "Cannot download file for task_id=%s from %s: %s",
                            task_id,
                            out_file,
                            err,
                        )
            # END_BLOCK_PER_FILE_DOWNLOAD

            # START_BLOCK_RMTREE_GATE
            # Post-loop rmtree on full success only (both error lists empty); own fresh
            # client. Any error preserves the remote dir for retry / debugging.
            if not transient_errors and not permanent_errors:
                async with self._operations.get_sftp(ip) as sftp:
                    await sftp.rmtree(path_type(remote_dir))
            # END_BLOCK_RMTREE_GATE
        except Exception as err:
            # Catch-all: whole-session failure (get_sftp raising, or a non-(OSError|SFTPError)
            # escape) is transient — the remote dir is preserved.
            self._log.warning("Cannot scp from %s: %s", remote_dir, err)
            transient_errors.append((remote_dir, err))
        # END_BLOCK_DOWNLOAD_OUTPUTS
        return meta_add, transient_errors, permanent_errors
