## MODIFIED Requirements

### Requirement: Layer direction (R3)

The system SHALL enforce a layering discipline where the dependency
direction flows `entrypoints → infra → application → domain`. Imports
SHALL follow this direction; violations (e.g. `infra` importing from
`application`) SHALL be detected by the `layers` contract check.

The composition root (`yascheduler.entrypoints.di`) is a resident of
`yascheduler.entrypoints`; its imports of adapter and application
symbols flow in the layer direction and are allowed.

#### Scenario: Adapter imports domain — allowed

- **WHEN** a module in `yascheduler.infra` imports a symbol from `yascheduler.domain`
- **THEN** the `layers` contract reports no violation

#### Scenario: Application imports domain — allowed

- **WHEN** a module in `yascheduler.application` imports a symbol from `yascheduler.domain`
- **THEN** the `layers` contract reports no violation

#### Scenario: Application imports infra — violation

- **WHEN** a module in `yascheduler.application` imports a symbol from `yascheduler.infra`
- **THEN** the `layers` contract reports a violation (driven layers may not import upward into driving adapters)

#### Scenario: Application imports from entrypoints — violation

- **WHEN** a module in `yascheduler.application` imports a symbol from `yascheduler.entrypoints`
- **THEN** the `layers` contract reports a violation

#### Scenario: Composition root imports from infra — allowed

- **WHEN** `yascheduler.entrypoints.di` imports `PostgresUnitOfWork`, `SSHMachineRepository`, `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`, `CloudProvisionerImpl`, `resolve_adapter`, and `webhook_handler` from `yascheduler.infra`
- **THEN** the `layers` contract reports no violation (composition root is a resident of `yascheduler.entrypoints` and its imports flow in the layer direction)

### Requirement: Cross-package facade imports (R2)

The system SHALL import symbols from another package via that package's
`__init__.py` only. For the three architectural layers, the layer's
`__init__.py` is the sole public surface for cross-layer consumers:

- `yascheduler.infra/__init__.py` — sole entry point for `application` and composition root to consume adapter symbols (repository, three operations collaborators, cloud provisioner, schema initializer, webhook handler, retry exceptions).
- `yascheduler.application/__init__.py` — sole entry point for `adapters` and composition root to consume application symbols (unit of work, orchestrator, message bus).
- `yascheduler.domain/__init__.py` — sole entry point for `adapters`, `application`, and composition root to consume domain symbols.

Subpackage facades (`yascheduler.infra.ssh`, `yascheduler.infra.cloud`,
`yascheduler.infra.persistence`, `yascheduler.infra.notifier`) are
internal organization of the `adapters` layer; cross-layer consumers
SHALL NOT import from them directly. Direct imports of submodules from
outside the package bypass the public surface and SHALL NOT appear in
any import.

#### Scenario: Adapter imports Task via domain facade

- **WHEN** a module in `yascheduler.infra` is added and needs to import `Task`
- **THEN** it uses `from yascheduler.domain import Task`, not `from yascheduler.domain.model import Task`

#### Scenario: Application imports adapter symbols via infra layer facade

- **WHEN** a module in `yascheduler.application` needs to import `SSHMachineRepository`, `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`, or `CloudProvisionerImpl`
- **THEN** it uses `from yascheduler.infra import SSHMachineRepository, TaskDeployer, OutputDownloader, OccupancyChecker, CloudProvisionerImpl`, not `from yascheduler.infra.ssh import SSHMachineRepository` or `from yascheduler.infra.ssh.repository import SSHMachineRepository`

#### Scenario: Composition root imports use layer facades

- **WHEN** a module in the composition root (`entrypoints/di.py`, `entrypoints/client.py`) imports a symbol from any layer
- **THEN** the import goes through the layer's `__init__.py` (e.g. `from yascheduler.infra import webhook_handler`), not through a subpackage facade or deep submodule path

#### Scenario: Within-layer cross-subpackage imports also use the layer facade

- **WHEN** a module in `yascheduler.infra.cli` needs `SSHMachineRepository` (which lives in `yascheduler.infra.ssh`)
- **THEN** it imports via `from yascheduler.infra import SSHMachineRepository` — the layer facade is the single public surface, even for sibling subpackages within the same layer

### Requirement: Domain package facade contents

The `yascheduler/domain/__init__.py` module SHALL be the layer facade
for the `domain` layer, re-exporting the domain model, events,
exceptions, and port Protocols that cross-layer consumers need. The
facade is the sole public surface for cross-layer consumers; direct
imports of `yascheduler.domain.model` or `yascheduler.domain.ports`
from outside the layer SHALL NOT appear.

#### Scenario: Domain facade exposes all required categories

- **WHEN** a consumer imports `from yascheduler.domain import Task, TaskCreated, DomainError, TaskRepository, NodeRepository, MachineRepository, MachineSession, CloudProvisioner`
- **THEN** all symbols resolve without ImportError

### Requirement: Extended facade contents (lazy publication driven by consumers)

The system SHALL re-export symbols from the infra layer facade
(`yascheduler/infra/__init__.py`), application layer facade
(`yascheduler/application/__init__.py`), and subpackage facades
(`yascheduler/infra/notifier/__init__.py`, `yascheduler/infra/cloud/__init__.py`,
`yascheduler/infra/persistence/__init__.py`) that external consumers already
import from their deep submodules. See the respective `__init__.py` files for
the exact re-export lists.

#### Scenario: Infra layer facade exposes the cross-layer surface

- **WHEN** a consumer imports `from yascheduler.infra import SSHMachineRepository, TaskDeployer, OutputDownloader, OccupancyChecker, AllSSHRetryExc, SFTPRetryExc, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork`
- **THEN** all eleven symbols resolve without ImportError

#### Scenario: Application facade exposes UoW, Orchestrator, MessageBus, submit_task

- **WHEN** a consumer imports `from yascheduler.application import AbstractUnitOfWork, Orchestrator, MessageBus, submit_task`
- **THEN** all four symbols resolve without ImportError
