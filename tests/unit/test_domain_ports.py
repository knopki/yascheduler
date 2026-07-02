# FILE: tests/unit/test_domain_ports.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Structural conformance tests for domain port Protocols via isinstance checks.
#   SCOPE: TaskRepository, NodeRepository, MachineRepository, MachineSession, MachineOperations, CloudProvisioner Protocols.
#   DEPENDS: none
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_task_repository_protocol - Stub with all TaskRepository methods passes isinstance
#   test_node_repository_protocol - Stub with all NodeRepository methods passes isinstance
#   test_machine_repository_protocol - Stub with all MachineRepository methods passes isinstance
#   test_machine_session_protocol - Stub with all MachineSession methods passes isinstance
#   test_machine_operations_protocol - Stub with all MachineOperations methods passes isinstance
#   test_cloud_provisioner_protocol - Stub with all CloudProvisioner methods passes isinstance
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - StubNodeRepository.enable/disable/remove take node_id: NodeId (node-id-keyed-mutators port change).
#   PREVIOUS_CHANGE: v1.5.0 - Update StubNodeRepository.add→insert, add get_by_id; StubCloudProvisioner.allocate returns NewNode; for add-node-id-identity port changes.
# END_CHANGE_SUMMARY

# ruff: noqa: ANN401

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import PurePath
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from yascheduler.domain.model import (
    ConnectedMachine,
    NewNode,
    NewTask,
    Node,
    NodeId,
    ProcessResult,
    Task,
    TaskId,
    TaskStatus,
)
from yascheduler.domain.ports import (
    CloudProvisioner,
    MachineOperations,
    MachineRepository,
    MachineSession,
    NodeRepository,
    TaskRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
    from pathlib import Path
    from re import Pattern

    from yascheduler.domain import Engine, EngineRepository


class StubTaskRepository:
    async def get(self, task_id: TaskId) -> Task | None:
        raise NotImplementedError

    async def save(self, task: Task) -> None:
        pass

    async def list_by_status(
        self, statuses: set[TaskStatus], *, limit: int | None = None
    ) -> list[Task]:
        return []

    async def insert(self, new_task: NewTask) -> Task:
        raise NotImplementedError

    async def list_by_jobs(self, job_ids: list[TaskId]) -> list[Task]:
        return []

    async def update_status(self, task_id: TaskId, status: TaskStatus) -> None:
        pass

    async def list_ids_by_ip_and_status(
        self, ip: str, status: TaskStatus
    ) -> list[TaskId]:
        return []

    async def count_by_status(self) -> dict[TaskStatus, int]:
        return {}


class StubNodeRepository:
    async def get(self, ip: str) -> Node | None:
        raise NotImplementedError

    async def list_enabled(self) -> list[Node]:
        return []

    async def list_disabled(self) -> list[Node]:
        return []

    async def get_by_id(self, node_id: NodeId) -> Node | None:
        raise NotImplementedError

    async def insert(self, new_node: NewNode) -> Node:
        raise NotImplementedError

    async def add_tmp(self, cloud: str) -> str:
        return "prov-tmp"

    async def update(self, node: Node) -> None:
        pass

    async def enable(self, node_id: NodeId) -> None:
        pass

    async def disable(self, node_id: NodeId) -> None:
        pass

    async def remove(self, node_id: NodeId) -> None:
        pass

    async def list_all(self) -> list[Node]:
        return []

    async def get_by_ips(self, ips: list[str]) -> dict[str, Node]:
        return {}

    async def count_by_status(self) -> dict[bool, int]:
        return {}


def _make_session_stub() -> ConnectedMachine:
    return ConnectedMachine(ip="10.0.0.1", platform="linux", ncpus=1)


class StubMachineSession(MachineSession):
    """Stub MachineSession covering the full Protocol surface."""

    @property
    def ip(self) -> str:
        return "10.0.0.1"

    @property
    def machine(self) -> ConnectedMachine:
        return _make_session_stub()

    @property
    def is_closed(self) -> bool:
        return False

    def occupy(self) -> None:
        pass

    def release(self) -> None:
        pass

    def update(self, machine: ConnectedMachine) -> None:
        pass

    @property
    def adapter(self) -> Any:
        return MagicMock()

    @property
    def platforms(self) -> Sequence[str]:
        return ("linux",)

    @property
    def data_dir(self) -> PurePath:
        return PurePath("./data")

    @property
    def engines_dir(self) -> PurePath:
        return PurePath("./data/engines")

    @property
    def tasks_dir(self) -> PurePath:
        return PurePath("./data/tasks")

    @property
    def path(self) -> type[PurePath]:
        return PurePath

    @property
    def quote(self) -> Callable[[str], str]:
        return lambda s: s

    @property
    def hostname(self) -> str:
        return "host"

    async def run(self, cmd: str) -> ProcessResult:
        return ProcessResult(exit_code=0)

    async def run_full(self, cmd: str) -> Any:
        return MagicMock(returncode=0)

    async def run_bg(self, cmd: str, *, cwd: str | None = None) -> None:
        pass

    async def upload(self, local: Path, remote: str) -> None:
        pass

    def open_sftp(self) -> Any:
        @asynccontextmanager
        async def _ctx() -> AsyncGenerator[Any, None]:
            yield MagicMock()

        return _ctx()

    async def get_cpu_cores(self) -> int:
        return 1

    async def setup_node(self, engines: EngineRepository) -> None:
        pass

    async def pgrep(
        self, pattern: str | Pattern[str], full: bool = True
    ) -> AsyncGenerator[Any, None]:
        return
        yield  # type: ignore[unreachable]

    async def list_processes(self) -> AsyncGenerator[Any, None]:
        return
        yield  # type: ignore[unreachable]

    def install_monitor(
        self,
        *,
        interval: float,
        check_factory: Callable[[], Awaitable[bool]],
        on_free: Callable[[], None],
    ) -> None:
        pass

    def cancel_monitor(self) -> None:
        pass


async def _empty_async_gen() -> Any:
    return
    yield  # type: ignore[unreachable]


class StubMachineRepository(MachineRepository):
    async def connect(
        self,
        ip: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
    ) -> MachineSession:
        return StubMachineSession()

    async def disconnect(self, ip: str) -> None:
        pass

    async def disconnect_all(self) -> None:
        pass

    def list_free(self, platforms: list[str] | None) -> list[MachineSession]:
        return []

    def list_connected(self) -> list[MachineSession]:
        return []

    def get_session(self, ip: str) -> MachineSession | None:
        return None

    def contains(self, ip: str) -> bool:
        return False

    def __len__(self) -> int:
        return 0

    def __contains__(self, ip: str) -> bool:
        return False


class StubMachineOperations:
    async def run(self, session: StubMachineSession, cmd: str) -> ProcessResult:
        return ProcessResult(exit_code=0)

    async def run_full(self, session: StubMachineSession, cmd: str) -> Any:
        return MagicMock(returncode=0)

    async def run_bg(
        self, session: StubMachineSession, cmd: str, *, cwd: str | None = None
    ) -> None:
        pass

    async def setup_node(
        self, session: StubMachineSession, engines: EngineRepository
    ) -> None:
        pass

    async def occupancy_check(
        self, session: StubMachineSession, config: Engine
    ) -> bool:
        return False

    async def download_outputs(
        self,
        session: StubMachineSession,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: TaskId | None = None,
    ) -> tuple[
        list[tuple[str, Any]],
        list[tuple[str | None, Exception]],
        list[tuple[str | None, Exception]],
    ]:
        return ([], [], [])

    def start_occupancy_check(
        self, session: StubMachineSession, config: Engine
    ) -> None:
        pass

    async def start_task_on_machine(
        self,
        session: StubMachineSession,
        engine: Engine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool:
        return True

    async def get_cpu_cores(self, session: StubMachineSession) -> int:
        return 0


class StubCloudProvisioner:
    async def allocate(self, provider: str) -> NewNode:
        raise NotImplementedError

    async def deallocate(self, cloud: str, ip: str) -> None:
        pass

    def select_provider(
        self, platforms: list[str], current_counts: dict[str, int]
    ) -> str | None:
        return None

    async def stop(self) -> None:
        pass


# START_CONTRACT: test_task_repository_protocol
#   PURPOSE: Verify a stub implementing all TaskRepository methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_task_repository_protocol
def test_task_repository_protocol() -> None:
    stub = StubTaskRepository()
    assert isinstance(stub, TaskRepository)


# START_CONTRACT: test_node_repository_protocol
#   PURPOSE: Verify a stub implementing all NodeRepository methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_node_repository_protocol
def test_node_repository_protocol() -> None:
    stub = StubNodeRepository()
    assert isinstance(stub, NodeRepository)


# START_CONTRACT: test_machine_repository_protocol
#   PURPOSE: Verify a stub implementing all MachineRepository methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_machine_repository_protocol
def test_machine_repository_protocol() -> None:
    stub = StubMachineRepository()
    assert isinstance(stub, MachineRepository)


# START_CONTRACT: test_machine_session_protocol
#   PURPOSE: Verify a stub implementing all MachineSession methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_machine_session_protocol
def test_machine_session_protocol() -> None:
    stub = StubMachineSession()
    assert isinstance(stub, MachineSession)


# START_CONTRACT: test_machine_operations_protocol
#   PURPOSE: Verify a stub implementing all MachineOperations methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_machine_operations_protocol
def test_machine_operations_protocol() -> None:
    stub = StubMachineOperations()
    assert isinstance(stub, MachineOperations)


# START_CONTRACT: test_cloud_provisioner_protocol
#   PURPOSE: Verify a stub implementing all CloudProvisioner methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_provisioner_protocol
def test_cloud_provisioner_protocol() -> None:
    stub = StubCloudProvisioner()
    assert isinstance(stub, CloudProvisioner)
