## MODIFIED Requirements

### Requirement: Domain package facade contents

`yascheduler/domain/__init__.py` SHALL re-export the following
categories of symbols as the public surface of the domain layer:

- **Events** (already exported today; no regression): `DomainEvent`, `Event`, `TaskAbandoned`, `TaskAllocated`, `TaskCompleted`, `TaskCreated`, `TaskFailed`.
- **Model**: `Task` and related domain entities defined in `yascheduler.domain.model`.
- **Engine types**: `Engine`, `EngineRepository`, `LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`, `Deploy` from `yascheduler.domain.engine` (re-exported via `yascheduler.domain.model`).
- **Exceptions**: the existing `DomainError` tree from `yascheduler.domain.exceptions` (no new symbols added by this change).
- **Ports**: `TaskRepository`, `NodeRepository`, `MachineGateway`, `CloudProvisioner` Protocols from `yascheduler.domain.ports`.

#### Scenario: Domain facade exposes all required categories
- **WHEN** a consumer imports `from yascheduler.domain import Task, TaskCreated, DomainError, TaskRepository, NodeRepository, MachineGateway, CloudProvisioner`
- **THEN** all symbols resolve without ImportError

#### Scenario: Domain facade exposes Engine types
- **WHEN** a consumer imports `from yascheduler.domain import Engine, EngineRepository, Deploy, LocalFilesDeploy, LocalArchiveDeploy, RemoteArchiveDeploy`
- **THEN** all six symbols resolve without ImportError

#### Scenario: Domain exception tree unchanged
- **WHEN** the existing `DomainError` tree in `yascheduler/domain/exceptions.py` is inspected after the change
- **THEN** no new exception classes are added by this change (existing hierarchy preserved)

### Requirement: Extended facade contents (lazy publication driven by consumers)

The following subpackage facades SHALL re-export the symbols that
external consumers already import from their deep submodules. This is
the lazy publication policy in operation: each symbol is added because
a real cross-package consumer requires it, and R2 retroactive
enforcement demands the facade form.

- **`yascheduler/infra/__init__.py`** (the adapters LAYER facade — sole public surface for cross-layer consumers and composition root) SHALL re-export:
  - `SSHMachineGateway`, `AllSSHRetryExc`, `SFTPRetryExc` from `.ssh` (consumed by `yascheduler.application.*` at module level for backoff and under `TYPE_CHECKING` for type hints; also consumed within the `adapters` layer by `cli.*` and `cloud.manager`).
  - `CloudProvisionerImpl` from `.cloud` (consumed by `yascheduler.application.*` under `TYPE_CHECKING` and by the composition root `yascheduler.entrypoints.di`).
  - `CloudAdapter` from `.cloud` (consumed by the composition root `yascheduler.entrypoints.di` for adapter typing).
  - `apply_schema` from `.persistence` (consumed by `adapters.cli.init`).
  - `webhook_handler` from `.notifier` (consumed by the composition root `yascheduler.entrypoints.di`).
  - `PostgresUnitOfWork` from `.persistence` (consumed by the composition root `yascheduler.entrypoints.di` for UoW wiring).
- **`yascheduler/application/__init__.py`** SHALL re-export:
  - `AbstractUnitOfWork` from `.uow` (consumed by `adapters.cli.manage_node`).
  - `Orchestrator` from `.orchestrator` (consumed by `adapters.cli.daemonize` and the composition root `yascheduler.entrypoints.di`).
  - `MessageBus` from `.message_bus` (consumed by `adapters.persistence.postgres_uow` and the composition root `yascheduler.entrypoints.di`).
  - `submit_task` from `.submit_task` (consumed by the composition root `yascheduler.entrypoints.di`).
- **`yascheduler/infra/notifier/__init__.py`** SHALL re-export:
  - `webhook_handler` from `.webhook` (consumed by the composition root via the `adapters` layer facade).
- **`yascheduler/infra/cloud/__init__.py`** SHALL re-export:
  - `get_rnd_name` from `.utils` (consumed within the `cloud` subpackage by `providers/*`).
  - (Existing re-exports `CloudProvisionerImpl`, `CloudAdapter`, `PCloudConfig`, `get_key_name`, etc. preserved.)
- **`yascheduler/infra/persistence/__init__.py`** SHALL re-export:
  - `apply_schema` from `.postgres_schema` (consumed by `adapters.cli.init` via the `adapters` layer facade).
  - `PostgresUnitOfWork` from `.postgres_uow` (consumed by the composition root `yascheduler.entrypoints.di` via the `adapters` layer facade).
  - (Preserved existing `load_query` and `UnitOfWorkNotInitializedError`.)
- **`yascheduler/config/__init__.py`** SHALL re-export:
  - `AzureImageReference` from `.cloud` (consumed by `adapters.cloud.providers.az` under `TYPE_CHECKING`).

`yascheduler/config/__init__.py` SHALL NOT re-export `Engine`,
`EngineRepository`, `Deploy`, `LocalFilesDeploy`, `LocalArchiveDeploy`, or
`RemoteArchiveDeploy` — these symbols move to `yascheduler.domain` in the
`engine-to-domain-frozen` change. The physical files
`yascheduler/config/engine.py` and `yascheduler/config/engine_repository.py`
SHALL NOT exist after this change; engine domain types live in
`yascheduler/domain/engine.py` and are re-exported via
`yascheduler.domain.model` and `yascheduler.domain`.

The re-exports enumerated here are the complete set required to make
every pre-existing cross-package import R2-compliant, including
composition-root (`yascheduler.entrypoints.di`) wiring. (Engine types are
now R2-compliant via `yascheduler.domain`, not `yascheduler.config`.)

#### Scenario: Adapters layer facade exposes the cross-layer surface
- **WHEN** a consumer imports `from yascheduler.infra import SSHMachineGateway, AllSSHRetryExc, SFTPRetryExc, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork`
- **THEN** all eight symbols resolve without ImportError

#### Scenario: Application facade exposes UoW, Orchestrator, MessageBus, submit_task
- **WHEN** a consumer imports `from yascheduler.application import AbstractUnitOfWork, Orchestrator, MessageBus, submit_task`
- **THEN** all four symbols resolve without ImportError

#### Scenario: Notifier subpackage facade exposes webhook_handler
- **WHEN** a consumer imports `from yascheduler.infra.notifier import webhook_handler`
- **THEN** the symbol resolves without ImportError

#### Scenario: Cloud subpackage facade exposes get_rnd_name
- **WHEN** a consumer imports `from yascheduler.infra.cloud import get_rnd_name`
- **THEN** the symbol resolves without ImportError

#### Scenario: Persistence subpackage facade exposes apply_schema and PostgresUnitOfWork
- **WHEN** a consumer imports `from yascheduler.infra.persistence import apply_schema, PostgresUnitOfWork`
- **THEN** both symbols resolve without ImportError

#### Scenario: Config facade exposes AzureImageReference
- **WHEN** a consumer imports `from yascheduler.config import AzureImageReference`
- **THEN** the symbol resolves without ImportError

#### Scenario: Config facade no longer exposes Engine types
- **WHEN** a consumer attempts `from yascheduler.config import Engine, EngineRepository, Deploy, LocalFilesDeploy, LocalArchiveDeploy, RemoteArchiveDeploy`
- **THEN** `ImportError` is raised (the symbols are re-exported by `yascheduler.domain`, not `yascheduler.config`)

#### Scenario: Config engine modules removed
- **WHEN** the `yascheduler/config/` directory is inspected for `engine.py` and `engine_repository.py`
- **THEN** neither file exists; the engine domain types live in `yascheduler/domain/engine.py`