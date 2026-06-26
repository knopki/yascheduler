## MODIFIED Requirements

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
  - `ConfigCloud`, `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
    `ConfigCloudVastAI`, `AzureImageReference` from `.cloud_configs`
    (cloud-configs-to-infra-registry: the cloud config DTOs relocated from
    `yascheduler.config.cloud`; consumed by provider modules under
    `TYPE_CHECKING`, by `infra/cloud/protocols.py` at runtime, and by the
    composition root).
  - `CloudInitConfig` from `.cloud_init` (cloud-init-rename-and-prune: the
    cloud-init user-data renderer was renamed from `class CloudConfig` in
    `cloud_config.py` to `class CloudInitConfig` in `cloud_init.py` to
    disambiguate from the `ConfigCloud*` provider-config DTOs and from the
    unrelated domain `CloudConfig` Protocol in `domain/ports.py`; consumed by
    `infra/cloud/manager.py` and the cloud providers under
    `TYPE_CHECKING`/runtime).
  - (Existing re-exports `CloudProvisionerImpl`, `CloudAdapter`,
    `get_key_name`, `resolve_adapter`, etc. preserved.)
  - `PCloudConfig` SHALL NO LONGER be re-exported from
    `yascheduler.infra.cloud` (cloud-init-rename-and-prune: the
    single-implementer Protocol was collapsed into its sole concrete class
    `CloudInitConfig`; the Protocol is deleted from
    `infra/cloud/protocols.py`; the canonical type for cloud-init config
    parameters is now `CloudInitConfig`).
  - `CloudCapacity` SHALL NO LONGER be re-exported from
    `yascheduler.infra.cloud` (cloud-init-rename-and-prune: the dead
    dataclass was deleted; its last consumer was removed in the archived
    `cloud-provisioner-pure` change which rewrote `_clouds_get_capacity` to
    return `int`; the unrelated `CloudCapacityExhaustedError` domain
    exception in `domain/exceptions.py` is unaffected).
  - `CloudConfig` (the cloud-init renderer, NOT the domain Protocol) SHALL
    NO LONGER be re-exported from `yascheduler.infra.cloud`
    (cloud-init-rename-and-prune: the class was renamed to `CloudInitConfig`;
    the canonical import is `from yascheduler.infra.cloud import
    CloudInitConfig`).
- **`yascheduler/infra/persistence/__init__.py`** SHALL re-export:
  - `apply_schema` from `.postgres_schema` (consumed by `adapters.cli.init` via the `adapters` layer facade).
  - `PostgresUnitOfWork` from `.postgres_uow` (consumed by the composition root `yascheduler.entrypoints.di` via the `adapters` layer facade).
  - (Preserved existing `load_query` and `UnitOfWorkNotInitializedError`.)
- **`yascheduler/config/__init__.py`** SHALL re-export:
  - `Config` from `.config` (consumed by daemon/CLI entry points until P4).
  - `ConfigDb` from `.db` (consumed by `infra/persistence/*` until P4).
  - `ConfigLocal` from `.local` (consumed by orchestrator/cloud manager until P4).
  - `ConfigRemote` from `.remote` (consumed by orchestrator/cloud manager until P4).
  - `AzureImageReference` SHALL NO LONGER be re-exported from `yascheduler.config`
    (cloud-configs-to-infra-registry: the symbol moved to
    `yascheduler.infra.cloud`; the canonical import is
    `from yascheduler.infra.cloud import AzureImageReference`).
  - `ConfigCloud`, `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
    `ConfigCloudVastAI` SHALL NO LONGER be re-exported from `yascheduler.config`
    (cloud-configs-to-infra-registry: the symbols moved to
    `yascheduler.infra.cloud`; the canonical import is
    `from yascheduler.infra.cloud import ...`).

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

#### Scenario: Cloud subpackage facade exposes cloud config DTOs
- **WHEN** a consumer imports `from yascheduler.infra.cloud import ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference`
- **THEN** all six symbols resolve without ImportError (the DTOs were relocated from
  `yascheduler.config.cloud`; the cloud subpackage facade is now the canonical path)

#### Scenario: Cloud subpackage facade exposes CloudInitConfig
- **WHEN** a consumer imports `from yascheduler.infra.cloud import CloudInitConfig`
- **THEN** the symbol resolves without ImportError (the cloud-init renderer was
  renamed from `CloudConfig` in `cloud_config.py` to `CloudInitConfig` in
  `cloud_init.py` in the `cloud-init-rename-and-prune` change)

#### Scenario: Cloud subpackage facade no longer re-exports PCloudConfig
- **WHEN** a consumer attempts `from yascheduler.infra.cloud import PCloudConfig`
- **THEN** `ImportError` is raised (the single-implementer Protocol was collapsed
  into its sole concrete class `CloudInitConfig`; the Protocol is deleted from
  `infra/cloud/protocols.py`; the canonical type for cloud-init config params is
  `CloudInitConfig`)

#### Scenario: Cloud subpackage facade no longer re-exports CloudCapacity
- **WHEN** a consumer attempts `from yascheduler.infra.cloud import CloudCapacity`
- **THEN** `ImportError` is raised (the dead dataclass was deleted; its last
  consumer was removed in the archived `cloud-provisioner-pure` change; the
  unrelated `CloudCapacityExhaustedError` domain exception in
  `domain/exceptions.py` is NOT affected and remains importable from
  `yascheduler.domain`)

#### Scenario: Cloud subpackage facade no longer re-exports the infra CloudConfig renderer
- **WHEN** a consumer attempts `from yascheduler.infra.cloud import CloudConfig`
- **THEN** `ImportError` is raised for the renderer (the class was renamed to
  `CloudInitConfig`; the canonical import is `from yascheduler.infra.cloud
  import CloudInitConfig`). Note: `from yascheduler.domain import CloudConfig`
  continues to resolve — that is the unrelated domain Protocol (the 6-field
  provider-config contract in `domain/ports.py`), which this change does NOT
  touch.

#### Scenario: Persistence subpackage facade exposes apply_schema and PostgresUnitOfWork
- **WHEN** a consumer imports `from yascheduler.infra.persistence import apply_schema, PostgresUnitOfWork`
- **THEN** both symbols resolve without ImportError

#### Scenario: Config facade no longer re-exports cloud config DTOs
- **WHEN** a consumer imports `from yascheduler.config import ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference`
- **THEN** ImportError is raised (the symbols moved to `yascheduler.infra.cloud`; the
  canonical import path is `from yascheduler.infra.cloud import ...`)

#### Scenario: Config facade no longer exposes Engine types
- **WHEN** a consumer attempts `from yascheduler.config import Engine, EngineRepository, Deploy, LocalFilesDeploy, LocalArchiveDeploy, RemoteArchiveDeploy`
- **THEN** `ImportError` is raised (the symbols are re-exported by `yascheduler.domain`, not `yascheduler.config`)

#### Scenario: Config engine modules removed
- **WHEN** the `yascheduler/config/` directory is inspected for `engine.py` and `engine_repository.py`
- **THEN** neither file exists; the engine domain types live in `yascheduler/domain/engine.py`