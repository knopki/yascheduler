## Purpose

Define two factory seams that wire the daemon dependency graph and the
CLI dependency graph. Each factory builds only the adapters its entry
point needs.

## Requirements

### Requirement: Daemon dependency factory

The system SHALL provide a factory that wires the daemon dependency
graph from a configuration. The graph SHALL include the task
orchestrator, a unit-of-work factory, a connected-machine repository,
and the stateless collaborators that deploy tasks, download outputs,
and check occupancy.

#### Scenario: the daemon graph shares one connected-machine repository

- **WHEN** the daemon factory builds its graph without pre-built clouds
- **THEN** the orchestrator and the cloud provisioner use the same connected-machine repository, so a machine connected during cloud allocation is visible to the next orchestrator cycle without a second connection

#### Scenario: pre-built clouds can be injected

- **WHEN** the daemon factory is called with a pre-built cloud provisioner
- **THEN** the resulting daemon graph uses the injected provisioner, and the orchestrator uses a connected-machine repository built by the factory

### Requirement: CLI dependency factory

The system SHALL provide a factory that wires the CLI dependency graph
from a configuration. The graph SHALL stay within one process. It
builds the unit-of-work factory, the engines, and the submit use case.
A CLI command built from this graph SHALL exit with no daemon loop or
SSH pool left running.

#### Scenario: a CLI command does not start the daemon

- **WHEN** a CLI command obtains its dependencies from the CLI factory
- **THEN** no background daemon loop runs and no SSH pool opens for that command

### Requirement: CLI dependency seam on the Python client

The Python client SHALL accept a CLI dependency factory as a
testability seam. When the caller supplies no factory, the client
SHALL use the CLI dependency factory.

#### Scenario: a caller injects a CLI dependency factory

- **WHEN** the Python client is built with a caller-supplied factory
- **THEN** each task query builds its CLI dependencies from the injected factory, and the default CLI factory is not used
