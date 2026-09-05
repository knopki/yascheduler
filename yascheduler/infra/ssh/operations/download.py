"""OutputDownloader — per-file SFTP-isolated download with retry, error classification, conservative post-loop rmtree. Stateless: takes (log) at construction, (session, ...) per call."""
# region MODULE_CONTRACT
# PURPOSE: Per-file SFTP-isolated download with retry, error classification, and conservative post-loop rmtree. Stateless: session passed per call.
# SCOPE: OutputDownloader class and my_retry partial (canonical location).
# DEPENDENCIES: USES API: asyncssh (SFTPError)
# KEYWORDS: download, sftp, output, retry, rmtree, OutputDownloader
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from asyncssh.sftp import SFTPError

from yascheduler.infra.ssh.platform.types import SFTPRetryExc
from yascheduler.shared import retry

if TYPE_CHECKING:
    from pathlib import Path

    from yascheduler.domain import MachineSession, TaskId

__all__ = ["OutputDownloader", "my_retry"]
logger = logging.getLogger(__name__)
my_retry = partial(retry, on=SFTPRetryExc, max_time=60)


# region CLASS_OutputDownloader
# PURPOSE: Per-file SFTP-isolated download with retry and error classification.
class OutputDownloader:
    """Per-file SFTP-isolated download with retry and error classification.

    Opens a FRESH SFTP client per file (dead-connection blast radius bounded
    to one file). Classifies per-file exceptions into transient (SFTPRetryExc)
    or permanent (everything else). Removes the remote dir tree ONCE only on
    full success (both error lists empty). Stateless: takes (log) at
    construction, (session, ...) per call. Returns a 4-tuple
    (local_folder, remote_folder, transient_errors, permanent_errors).
    """

    # region METHOD_download_outputs
    # PURPOSE: Per-file SFTP-isolated download with retry, error classification, conservative post-loop rmtree.
    async def download_outputs(
        self,
        session: MachineSession,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: TaskId | None = None,
    ) -> tuple[
        str,
        str,
        list[tuple[str | None, Exception]],
        list[tuple[str | None, Exception]],
    ]:
        """Per-file SFTP-isolated download with retry, error classification, conservative post-loop rmtree."""
        # region BLOCK_download_outputs
        local_folder = str(local_dir)
        remote_folder = remote_dir
        transient_errors: list[tuple[str | None, Exception]] = []
        permanent_errors: list[tuple[str | None, Exception]] = []
        path_type = session.path
        file_get_retry = my_retry()

        try:
            # region BLOCK_per_file_download
            # Fresh SFTP client per file: a dropped channel on file N invalidates only N's
            # retries. The inner try classifies ONLY sftp.get failures — a get_sftp OPEN
            # failure escapes to the outer handler as a session-level transient (not per-file).
            for out_file in files:
                async with session.open_sftp() as sftp:
                    try:
                        await file_get_retry(sftp.get)(
                            out_file,
                            local_dir,
                            preserve=True,
                        )
                    except (OSError, SFTPError) as err:
                        # region BLOCK_classify
                        if isinstance(err, SFTPRetryExc):
                            transient_errors.append((out_file, err))
                        else:
                            permanent_errors.append((out_file, err))
                        # endregion BLOCK_classify
                        logger.warning(
                            "Cannot download file for task_id=%s from %s: %s",
                            task_id,
                            out_file,
                            err,
                        )
            # endregion BLOCK_per_file_download

            # region BLOCK_rmtree_gate
            # Post-loop rmtree on full success only (both error lists empty); own fresh
            # client. Any error preserves the remote dir for retry / debugging.
            if not transient_errors and not permanent_errors:
                async with session.open_sftp() as sftp:
                    await sftp.rmtree(path_type(remote_dir))
            # endregion BLOCK_rmtree_gate
        except Exception as err:
            # Catch-all: whole-session failure (open_sftp raising, or a non-(OSError|SFTPError)
            # escape) is transient — the remote dir is preserved.
            logger.warning("Cannot scp from %s: %s", remote_dir, err)
            transient_errors.append((remote_dir, err))
        # endregion BLOCK_download_outputs
        return local_folder, remote_folder, transient_errors, permanent_errors

    # endregion METHOD_download_outputs


# endregion CLASS_OutputDownloader
