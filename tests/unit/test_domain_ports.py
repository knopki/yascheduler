# FILE: tests/unit/test_domain_ports.py
# VERSION: 1.0.0
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
#   LAST_CHANGE: v1.0.0 - Initial Protocol structural conformance tests
# END_CHANGE_SUMMARY

from pathlib import Path

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
    TaskRepository,
)


class StubTaskRepository:
    async def get(self, task_id: int) -> Task | None:
        raise NotImplementedError

    async def save(self, task: Task) -> None:
        pass

    async def list_by_status(self, statuses: set[TaskStatus]) -> list[Task]:
        return []


class StubNodeRepository:
    async def get(self, ip: str) -> Node | None:
        raise NotImplementedError

    async def list_enabled(self) -> list[Node]:
        return []

    async def list_disabled(self) -> list[Node]:
        return []

    async def add(self, node: Node) -> None:
        pass

    async def add_tmp(self, cloud: str, username: str = "root") -> str:
        return "prov-tmp"

    async def update(self, node: Node) -> None:
        pass

    async def enable(self, ip: str) -> None:
        pass

    async def disable(self, ip: str) -> None:
        pass

    async def remove(self, ip: str) -> None:
        pass


class StubMachineGateway:
    async def list_free(self, platforms: list[str] | None) -> list[ConnectedMachine]:
        return []

    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult:
        return ProcessResult(exit_code=0)

    async def upload(self, machine: ConnectedMachine, local: Path, remote: str) -> None:
        pass

    async def download(
        self, machine: ConnectedMachine, remote: str, local: Path
    ) -> None:
        pass


class StubCloudProvisioner:
    async def allocate(self, platforms: list[str]) -> Node:
        raise NotImplementedError

    async def deallocate(self, ip: str) -> None:
        pass

    async def capacity(self) -> dict[str, int]:
        return {}


# START_CONTRACT: test_task_repository_protocol
#   PURPOSE: Verify a stub implementing all TaskRepository methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_task_repository_protocol
def test_task_repository_protocol():
    stub = StubTaskRepository()
    assert isinstance(stub, TaskRepository)


# START_CONTRACT: test_node_repository_protocol
#   PURPOSE: Verify a stub implementing all NodeRepository methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_node_repository_protocol
def test_node_repository_protocol():
    stub = StubNodeRepository()
    assert isinstance(stub, NodeRepository)


# START_CONTRACT: test_machine_gateway_protocol
#   PURPOSE: Verify a stub implementing all MachineGateway methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_machine_gateway_protocol
def test_machine_gateway_protocol():
    stub = StubMachineGateway()
    assert isinstance(stub, MachineGateway)


# START_CONTRACT: test_cloud_provisioner_protocol
#   PURPOSE: Verify a stub implementing all CloudProvisioner methods satisfies the Protocol structurally.
#   INPUTS: { None }
#   OUTPUTS: { None - assertion passes if isinstance succeeds }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_provisioner_protocol
def test_cloud_provisioner_protocol():
    stub = StubCloudProvisioner()
    assert isinstance(stub, CloudProvisioner)
