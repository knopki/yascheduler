# FILE: tests/unit/test_domain_ports.py
# VERSION: 1.3.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Structural conformance tests for domain port Protocols via isinstance checks.
#   SCOPE: TaskRepository, NodeRepository, MachineGateway, CloudProvisioner Protocols.
#   DEPENDS: none
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_task_repository_protocol - Stub with all TaskRepository methods passes isinstance
#   test_node_repository_protocol - Stub with all NodeRepository methods passes isinstance
#   test_machine_gateway_protocol - Stub with all MachineGateway methods passes isinstance
#   test_cloud_provisioner_protocol - Stub with all CloudProvisioner methods passes isinstance
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - CloudProvisioner.select_provider returns str|None; NodeRepository.add_tmp drops username (collapse-provider-selection).
#   PREVIOUS_CHANGE: v1.2.0 - Update StubMachineGateway to satisfy extended MachineGateway Protocol (gateway-port-cleanup).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yascheduler.domain.model import (
    ConnectedMachine,
    Node,
    ProcessResult,
    Task,
    TaskStatus,
)
from yascheduler.domain.ports import (
    CloudProvisioner,
    MachineGateway,
    NodeRepository,
    OccupancyConfig,
    TaskExecutionEngine,
    TaskRepository,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path, PurePath


class StubTaskRepository:
    async def get(self, task_id: int) -> Task | None:
        raise NotImplementedError

    async def save(self, task: Task) -> None:
        pass

    async def list_by_status(
        self, statuses: set[TaskStatus], *, limit: int | None = None
    ) -> list[Task]:
        return []

    async def insert(self, task: Task) -> Task:
        raise NotImplementedError

    async def list_by_jobs(self, job_ids: list[int]) -> list[Task]:
        return []

    async def update_status(self, task_id: int, status: TaskStatus) -> None:
        pass

    async def list_ids_by_ip_and_status(self, ip: str, status: TaskStatus) -> list[int]:
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

    async def add(self, node: Node) -> None:
        pass

    async def add_tmp(self, cloud: str) -> str:
        return "prov-tmp"

    async def update(self, node: Node) -> None:
        pass

    async def enable(self, ip: str) -> None:
        pass

    async def disable(self, ip: str) -> None:
        pass

    async def remove(self, ip: str) -> None:
        pass

    async def list_all(self) -> list[Node]:
        return []

    async def get_by_ips(self, ips: list[str]) -> dict[str, Node]:
        return {}

    async def count_by_status(self) -> dict[bool, int]:
        return {}


class StubMachineGateway:
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
    ) -> ConnectedMachine:
        raise NotImplementedError

    async def disconnect(self, ip: str) -> None:
        pass

    async def disconnect_all(self) -> None:
        pass

    def list_free(self, platforms: list[str] | None) -> list[ConnectedMachine]:
        return []

    def list_connected(self) -> list[ConnectedMachine]:
        return []

    def contains(self, ip: str) -> bool:
        return False

    def get_machine_state(self, ip: str) -> ConnectedMachine | None:
        return None

    def update_machine(self, machine: ConnectedMachine) -> None:
        pass

    def __len__(self) -> int:
        return 0

    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult:
        return ProcessResult(exit_code=0)

    async def run_bg(
        self, machine: ConnectedMachine, cmd: str, *, cwd: str | None = None
    ) -> None:
        pass

    async def upload(self, machine: ConnectedMachine, local: Path, remote: str) -> None:
        pass

    async def download(
        self, machine: ConnectedMachine, remote: str, local: Path
    ) -> None:
        pass

    async def download_outputs(
        self,
        ip: str,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: int | None = None,
    ) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]:
        return ([], [])

    def start_occupancy_check(self, ip: str, config: OccupancyConfig) -> None:
        pass

    async def start_task_on_machine(
        self,
        machine: ConnectedMachine,
        engine: TaskExecutionEngine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool:
        return True

    async def get_cpu_cores(self, ip: str) -> int:
        return 0


class StubCloudProvisioner:
    async def allocate(self, provider: str) -> Node:
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


# START_CONTRACT: test_machine_gateway_protocol
#   PURPOSE: Verify a stub implementing all MachineGateway methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_machine_gateway_protocol
def test_machine_gateway_protocol() -> None:
    stub = StubMachineGateway()
    assert isinstance(stub, MachineGateway)


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
