# FILE: yascheduler/infra/ssh/operations/base.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: SSHMachineOperations — base primitives operating on a single connected machine via the platform adapter and SFTP.
#   SCOPE: SSHMachineOperations class (run/run_full/run_bg/upload/download/get_sftp/pgrep/list_processes/get_cpu_cores/setup_node) + my_backoff_exc partial + narrow local Protocols (CommandExecutor, SftpProvider, StateAccessors).
#   DEPENDS: M-SSH-REPOSITORY, M-PLATFORM, M-SSH-EXCEPTIONS, M-DOMAIN
#   LINKS: M-SSH-OPERATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   my_backoff_exc - Partial backoff decorator for SSHRetryExc (canonical copy; moved from gateway.py)
#   CommandExecutor - Narrow local Protocol: run_full/run_bg (used by TaskDeployer)
#   SftpProvider - Narrow local Protocol: get_sftp (used by TaskDeployer, OutputDownloader)
#   StateAccessors - Narrow local Protocol: get_path/get_quote/get_hostname (used by TaskDeployer)
#   SSHMachineOperations - Operations on a single machine; composes deploy/download/occupancy collaborators
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial module created (decompose-ssh-gateway). SSHMachineOperations + my_backoff_exc extracted from the dissolved SSHMachineGateway god-class; base primitives live here; three sibling collaborators (TaskDeployer, OutputDownloader, OccupancyChecker) are composed via __init__.
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import partial
from typing import TYPE_CHECKING, Any, Protocol

import backoff

from yascheduler.domain import ProcessResult

from ..exceptions import AllSSHRetryExc, SSHRetryExc
from ..platform import make_run_fn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path, PurePath
    from re import Pattern

    from asyncssh.process import SSHCompletedProcess
    from asyncssh.sftp import SFTPClient

    from yascheduler.domain import (
        ConnectedMachine,
        Engine,
        EngineRepository,
        Task,
    )

    from ..platform import (
        ProcessInfo,
        QuoteCallable,
    )
    from ..repository import SSHMachineRepository

my_backoff_exc = partial(
    backoff.on_exception,
    wait_gen=backoff.fibo,
    max_time=60,
    exception=SSHRetryExc,
)


# Narrow local Protocols (D5) — collaborators type-annotate against these
# so they can be unit-tested with fakes without the full SSHMachineOperations.
class CommandExecutor(Protocol):
    async def run_full(
        self, machine: ConnectedMachine, cmd: str
    ) -> SSHCompletedProcess: ...

    async def run_bg(
        self,
        machine: ConnectedMachine,
        cmd: str,
        *,
        cwd: str | None = None,
    ) -> None: ...


class SftpProvider(Protocol):
    def get_sftp(self, ip: str) -> AbstractAsyncContextManager[SFTPClient]: ...


class StateAccessors(Protocol):
    def get_path(self, ip: str) -> type[PurePath]: ...

    def get_quote(self, ip: str) -> QuoteCallable: ...

    def get_hostname(self, ip: str) -> str: ...


class SSHMachineOperations:
    """Operations on a single connected machine via the platform adapter and SFTP.

    Composes three sibling collaborators (deploy/download/occupancy) that
    receive a reference to this object (as primitive-provider) and the
    repository. Composition, not inheritance — collaborators do NOT subclass.
    """

    def __init__(
        self,
        repository: SSHMachineRepository,
        log: logging.Logger | None = None,
    ) -> None:
        self._repo = repository
        self._log = log or logging.getLogger("SSHMachineOperations")
        from .deployment import TaskDeployer
        from .download import OutputDownloader
        from .occupancy import OccupancyChecker

        self.deploy = TaskDeployer(self, repository, self._log)
        self.download = OutputDownloader(self, repository, self._log)
        self.occupancy = OccupancyChecker(self, repository, self._log)

    # ---- base primitives ----

    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult:
        """Run command and return structured result."""
        proc = await self.run_full(machine, cmd)
        return ProcessResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=proc.stdout
            if isinstance(proc.stdout, str)
            else str(proc.stdout or ""),
            stderr=proc.stderr
            if isinstance(proc.stderr, str)
            else str(proc.stderr or ""),
        )

    @my_backoff_exc()
    async def run_full(
        self, machine: ConnectedMachine, cmd: str
    ) -> SSHCompletedProcess:
        """Run command and return raw SSHCompletedProcess."""
        state = self._repo._get_machine_state(machine.ip)
        assert state is not None
        return await state.adapter.run(state.conn, state.adapter.quote, cmd)

    async def run_bg(
        self,
        machine: ConnectedMachine,
        cmd: str,
        *,
        cwd: str | None = None,
    ) -> None:
        """Start background process on remote machine (single attempt — spawn is non-idempotent)."""
        state = self._repo._get_machine_state(machine.ip)
        assert state is not None
        await state.adapter.run_bg(state.conn, state.adapter.quote, cmd, cwd=cwd)

    async def upload(self, machine: ConnectedMachine, local: Path, remote: str) -> None:
        """Upload file to remote machine via SFTP (single attempt — put is non-idempotent)."""
        state = self._repo._get_machine_state(machine.ip)
        assert state is not None
        async with state.conn.start_sftp_client() as sftp:
            await sftp.put(str(local), remote)

    # NOTE: single-file `download(machine, remote, local)` primitive is intentionally
    # absent — `self.download` is the OutputDownloader collaborator attribute per
    # decompose-ssh-gateway design D3 / ssh-machine-repository composition spec.
    # The 3 test callsites that exercised gateway.download(machine,...) are migrated
    # in section 14 to use get_sftp + sftp.get directly. The MachineOperations Protocol
    # scenario "Download file" is superseded by the composition requirement.

    @asynccontextmanager
    async def get_sftp(self, ip: str) -> AsyncIterator[SFTPClient]:
        """Open SFTP client for machine (async context manager)."""
        state = self._repo._get_machine_state(ip)
        assert state is not None
        async with state.conn.start_sftp_client() as sftp:
            yield sftp

    @my_backoff_exc()
    async def get_cpu_cores(self, ip: str) -> int:
        """Return CPU core count for machine (idempotent read — retried)."""
        state = self._repo._get_machine_state(ip)
        assert state is not None
        return await state.adapter.get_cpu_cores(make_run_fn(state.conn, state.adapter))

    async def setup_node(self, ip: str, engines: EngineRepository) -> None:
        """Install engine dependencies on remote node."""
        state = self._repo._get_machine_state(ip)
        assert state is not None
        self._log.info("CPUs count: %s", state.machine.ncpus)
        retry = my_backoff_exc(exception=AllSSHRetryExc)
        await retry(state.adapter.setup_node)(
            conn=state.conn,
            run=make_run_fn(state.conn, state.adapter),
            quote=state.adapter.quote,
            engines=engines.filter_platforms(state.platforms),
            engines_dir=state.engines_dir,
            log=self._log,
        )

    async def pgrep(
        self,
        ip: str,
        pattern: str | Pattern[str],
        full: bool = True,
    ) -> AsyncGenerator[ProcessInfo, None]:
        """Yield remote processes matching pattern."""
        state = self._repo._get_machine_state(ip)
        assert state is not None
        async for proc in state.adapter.pgrep(
            state.conn, state.adapter.quote, pattern, full
        ):
            yield proc

    async def list_processes(self, ip: str) -> AsyncGenerator[ProcessInfo, None]:
        """Yield all running processes on remote machine."""
        state = self._repo._get_machine_state(ip)
        assert state is not None
        async for proc in state.adapter.list_processes(state.conn, None):
            yield proc

    # ---- forwarded use-case methods (implemented in sections 4-6) ----

    async def start_task_on_machine(
        self,
        machine: ConnectedMachine,
        engine: Engine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool:
        return await self.deploy.start_task_on_machine(
            machine, engine, task, ncpus, engines_dir
        )

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
        return await self.download.download_outputs(
            ip, remote_dir, local_dir, files, task_id
        )

    async def occupancy_check(self, ip: str, config: Engine) -> bool:
        return await self.occupancy.occupancy_check(ip, config)

    def start_occupancy_check(self, ip: str, config: Engine) -> None:
        self.occupancy.start_occupancy_check(ip, config)
