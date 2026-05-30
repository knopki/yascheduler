## Purpose

Defines abstract port interfaces (typing.Protocol) for the domain layer: TaskRepository, NodeRepository, MachineGateway, and CloudProvisioner — contracts that infrastructure adapters must implement.

## Requirements

### Requirement: TaskRepository port

The system SHALL define a `TaskRepository` Protocol with async methods:
`get(task_id: int) -> Task | None`, `save(task: Task) -> None`,
`insert(task: Task) -> Task`,
`list_by_status(statuses: set[TaskStatus], limit: int | None) -> list[Task]`,
`list_by_jobs(job_ids: list[int]) -> list[Task]`,
`update_status(task_id: int, status: TaskStatus) -> None`,
`list_ids_by_ip_and_status(ip: str, status: TaskStatus) -> list[int]`.

#### Scenario: Repository method signatures are async
- **WHEN** a class implements `TaskRepository` with matching async method signatures
- **THEN** it satisfies the Protocol structurally

### Requirement: NodeRepository port

The system SHALL define a `NodeRepository` Protocol with async methods:
`get(ip: str) -> Node | None`, `list_enabled() -> list[Node]`,
`list_disabled() -> list[Node]`, `list_all() -> list[Node]`,
`add(node: Node) -> None`, `add_tmp(cloud: str, username: str) -> str`,
`update(node: Node) -> None`, `enable(ip: str) -> None`,
`disable(ip: str) -> None`, `remove(ip: str) -> None`,
`get_by_ips(ips: list[str]) -> dict[str, Node]`.

#### Scenario: Full node lifecycle through port
- **WHEN** a consumer calls `add`, `get`, `update`, `enable`, `disable`, `list_enabled`, `list_disabled`, `list_all`, `get_by_ips`, `remove` through the port
- **THEN** the Protocol defines all these operations with async signatures

### Requirement: MachineGateway port

The system SHALL define a `MachineGateway` Protocol with methods:
`list_free(platforms: list[str] | None) -> list[ConnectedMachine]`,
`run(machine: ConnectedMachine, cmd: str) -> ProcessResult`,
`upload(machine: ConnectedMachine, local: Path, remote: str) -> None`,
`download(machine: ConnectedMachine, remote: str, local: Path) -> None`.

All methods are async.

#### Scenario: List free machines filtered by platform
- **WHEN** `list_free(["linux", "debian-12"])` is called
- **THEN** returns only FREE ConnectedMachines with matching platforms

#### Scenario: Run command on machine
- **WHEN** `run(machine, "echo hello")` is called
- **THEN** returns a ProcessResult with exit_code and captured output

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(platforms: list[str]) -> Node`,
`deallocate(ip: str) -> None`,
`capacity() -> dict[str, int]`.

All methods are async.

#### Scenario: Allocate cloud node
- **WHEN** `allocate(["linux"])` is called
- **THEN** returns a Node with the provisioned IP

#### Scenario: Report capacity
- **WHEN** `capacity()` is called
- **THEN** returns a dict mapping provider names to available node counts

### Requirement: Ports are importable from domain

The system SHALL expose all port Protocols from `yascheduler.domain.ports`.

#### Scenario: Import ports for adapter implementation
- **WHEN** an adapter module imports `from yascheduler.domain.ports import TaskRepository`
- **THEN** the Protocol class is available for structural subtyping
