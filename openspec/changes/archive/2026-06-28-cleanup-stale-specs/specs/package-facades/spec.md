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
  - `apply_schema` from `.postgres_schema` (consumed by `entrypoints.cli.init` via the `infra` layer facade).
  - `PostgresUnitOfWork` from `.postgres_uow` (consumed by the composition root `yascheduler.entrypoints.di` via the `infra` layer facade).
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
SHALL NOT exist; the engine domain types live in `yascheduler/domain/engine.py`.

#### Scenario: Infra layer facade exposes the cross-layer surface

- **WHEN** a consumer imports `from yascheduler.infra import SSHMachineRepository, SSHMachineOperations, AllSSHRetryExc, SFTPRetryExc, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork`
- **THEN** all nine symbols resolve without ImportError

### Requirement: Documented private-symbol carve-outs

The system SHALL maintain an explicit, spec-documented list of deep-path
imports that are exempt from R2 (facade) enforcement because the symbols
are deliberately private (leading underscore) and MUST NOT be promoted to
any facade. As of this change, the list is empty: the prior carve-out for
`yascheduler/di.py: from .infra.cloud.adapters import _resolve_adapter`
is removed because the symbol was renamed to public `resolve_adapter` (in
the `review-hardening` change) and is now imported by the composition root
via the `infra` layer facade (`from yascheduler.infra import
resolve_adapter`), which is R2-compliant.

#### Scenario: No private-symbol carve-outs remain
- **WHEN** the R2 carve-out list is inspected
- **THEN** it is empty; every cross-package import in the codebase goes through a layer facade

#### Scenario: Private symbols stay on deep paths
- **WHEN** a leading-underscore symbol is needed by the composition root
- **THEN** it is NOT imported via a deep path that bypasses the layer facade; either it is promoted to public and re-exported by the facade, or it is not used across package boundaries at all