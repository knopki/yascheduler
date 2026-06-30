## MODIFIED Requirements

### Requirement: Extended facade contents (lazy publication driven by consumers)

The following subpackage facades SHALL re-export the symbols that
external consumers already import from their deep submodules. This is
the lazy publication policy in operation: each symbol is added because
a real cross-package consumer requires it, and R2 retroactive
enforcement demands the facade form.

- **`yascheduler/infra/__init__.py`** (the infra LAYER facade — sole public surface for cross-layer consumers and composition root) SHALL re-export:
  - `SSHMachineRepository`, `SSHMachineOperations`, `AllSSHRetryExc`, `SFTPRetryExc` from `.ssh` (consumed by `yascheduler.application.*` under `TYPE_CHECKING` for type hints; also consumed within the `infra` layer by `cloud.manager` and the composition root).
  - `CloudProvisionerImpl` from `.cloud` (consumed by `yascheduler.application.*` under `TYPE_CHECKING` and by the composition root `yascheduler.entrypoints.di`).
  - `CloudAdapter` from `.cloud` (consumed by the composition root `yascheduler.entrypoints.di` for adapter typing).
  - `apply_schema` from `.persistence` (consumed by `entrypoints.cli.init`).
  - `webhook_handler` from `.notifier` (consumed by the composition root `yascheduler.entrypoints.di`).
  - `PostgresUnitOfWork` from `.persistence` (consumed by the composition root `yascheduler.entrypoints.di` for UoW wiring).
- **`yascheduler/application/__init__.py`** SHALL re-export:
  - `AbstractUnitOfWork` from `.uow` (consumed by `entrypoints.cli.manage_node`).
  - `Orchestrator` from `.orchestrator` (consumed by `entrypoints.cli.daemonize` and the composition root `yascheduler.entrypoints.di`).
  - `MessageBus` from `.message_bus` (consumed by `infra.persistence.postgres_uow` and the composition root `yascheduler.entrypoints.di`).
  - `submit_task` from `.submit_task` (consumed by the composition root `yascheduler.entrypoints.di`).
- **`yascheduler/infra/notifier/__init__.py`** SHALL re-export:
  - `webhook_handler` from `.webhook` (consumed by the composition root via the `infra` layer facade).
- **`yascheduler/infra/cloud/__init__.py`** SHALL re-export:
  - `get_rnd_name` from `.utils` (consumed within the `cloud` subpackage by `providers/*`).
  - `ConfigCloud`, `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
    `ConfigCloudVastAI`, `AzureImageReference` from `.cloud_configs`
    (consumed by provider modules under `TYPE_CHECKING`, by
    `infra/cloud/protocols.py` at runtime, and by the composition root).
  - `CloudInitConfig` from `.cloud_init` (consumed by
    `infra/cloud/manager.py` and the cloud providers under
    `TYPE_CHECKING`/runtime).
  - (Existing re-exports `CloudProvisionerImpl`, `CloudAdapter`,
    `get_key_name`, `resolve_adapter`, etc. preserved.)
- **`yascheduler/infra/persistence/__init__.py`** SHALL re-export:
  - `apply_schema` from `.postgres_schema` (consumed by `entrypoints.cli.init` via the `infra` layer facade).
  - `PostgresUnitOfWork` from `.postgres_uow` (consumed by the composition root `yascheduler.entrypoints.di` via the `infra` layer facade).
  - (Preserved existing `load_query` and `UnitOfWorkNotInitializedError`.)

The re-exports enumerated here are the complete set required to make
every pre-existing cross-package import R2-compliant, including
composition-root (`yascheduler.entrypoints.di`) wiring.

#### Scenario: Infra layer facade exposes the cross-layer surface
- **WHEN** a consumer imports `from yascheduler.infra import SSHMachineRepository, SSHMachineOperations, AllSSHRetryExc, SFTPRetryExc, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork`
- **THEN** all nine symbols resolve without ImportError

#### Scenario: Application facade exposes UoW, Orchestrator, MessageBus, submit_task
- **WHEN** a consumer imports `from yascheduler.application import AbstractUnitOfWork, Orchestrator, MessageBus, submit_task`
- **THEN** all four symbols resolve without ImportError

#### Scenario: Notifier subpackage facade exposes webhook_handler
- **WHEN** a consumer imports `from yascheduler.infra.notifier import webhook_handler`
- **THEN** the symbol resolves without ImportError

#### Scenario: Cloud subpackage facade exposes get_rnd_name
- **WHEN** a consumer imports `from yascheduler.infra.cloud import get_rnd_name`
- **THEN** the symbol resolves without ImportError

#### Scenario: Cloud subpackage facade exposes cloud config DTOs
- **WHEN** a consumer imports `from yascheduler.infra.cloud import ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference`
- **THEN** all six symbols resolve without ImportError

#### Scenario: Cloud subpackage facade exposes CloudInitConfig
- **WHEN** a consumer imports `from yascheduler.infra.cloud import CloudInitConfig`
- **THEN** the symbol resolves without ImportError

#### Scenario: Persistence subpackage facade exposes apply_schema and PostgresUnitOfWork
- **WHEN** a consumer imports `from yascheduler.infra.persistence import apply_schema, PostgresUnitOfWork`
- **THEN** both symbols resolve without ImportError
