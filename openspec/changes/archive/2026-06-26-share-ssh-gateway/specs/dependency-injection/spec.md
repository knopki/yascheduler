## ADDED Requirements

### Requirement: make_daemon shares one SSHMachineGateway on the production path

On the `clouds is None` branch, `make_daemon` SHALL construct exactly one
`SSHMachineGateway` instance and inject the same instance into both
`CloudProvisionerImpl.machine_gateway` and `Orchestrator.gateway`. This
ensures a single `_machines` registry spans cloud setup (via `_setup_vm`) and
orchestrator runtime, so that connections opened during cloud allocation are
visible to the orchestrator and are reaped by `Orchestrator.stop()` via
`gateway.disconnect_all()`.

The pre-built-clouds (`clouds is not None`) branch is out of scope: it SHALL
continue to construct a fresh `SSHMachineGateway` for the orchestrator while
the caller-supplied `clouds` retain whatever gateway they were built with.
This branch is exercised only by unit tests and performs no real allocations.

This requirement exists to prevent two correctness defects that arise from
split registries: (1) every allocated cloud node leaks one SSH connection for
the process lifetime because the cloud gateway is never drained, and (2) the
orchestrator opens a second connection to each cloud VM because its
`contains(ip)` filter inspects only its own registry.

#### Scenario: clouds is None shares one gateway instance

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** the `SSHMachineGateway` instance passed as
  `CloudProvisionerImpl.machine_gateway` SHALL be the same object (`is`) as
  the instance passed as `Orchestrator.gateway`

#### Scenario: clouds is None constructs exactly one SSHMachineGateway

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `SSHMachineGateway(...)` SHALL be invoked exactly once across the
  construction of `CloudProvisionerImpl` and `Orchestrator`

#### Scenario: pre-built clouds path keeps its own gateway

- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the orchestrator SHALL be constructed with a `gateway` that is a
  fresh `SSHMachineGateway`, NOT taken from `my_clouds.machine_gateway`; the
  caller-supplied `clouds` instance SHALL be wired to the orchestrator
  unchanged

#### Scenario: cloud-allocation connections are visible to orchestrator

- **WHEN** a cloud node is allocated via `clouds.allocate(provider)` and
  `_setup_vm` connects it via `machine_gateway.connect(ip)`
- **THEN** a subsequent `_connect_machine_producer` cycle in the orchestrator
  SHALL observe `gateway.contains(ip) == True` for that node and SHALL NOT
  call `gateway.connect(ip)` again for it

#### Scenario: cloud-allocation connections are reaped at shutdown

- **WHEN** `Orchestrator.stop()` runs after one or more cloud nodes have been
  allocated on the `clouds is None` path
- **THEN** `gateway.disconnect_all()` SHALL close every connection opened by
  `_setup_vm`, leaving no cloud-setup SSH connection open at process exit
