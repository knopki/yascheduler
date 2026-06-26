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
  - `list_private_keys` from `.ssh` (consumed by the composition root `yascheduler.entrypoints.di` for orchestrator injection; ssh-keys-extraction-vastai-parser-fix).
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
  - (Existing re-exports `CloudProvisionerImpl`, `CloudAdapter`, `PCloudConfig`,
    `get_key_name`, `resolve_adapter`, etc. preserved.)
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

The re-exports enumerated here are the complete set required to make
every pre-existing cross-package import R2-compliant, including
composition-root (`yascheduler.entrypoints.di`) wiring.

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

#### Scenario: Cloud subpackage facade exposes cloud config DTOs
- **WHEN** a consumer imports `from yascheduler.infra.cloud import ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference`
- **THEN** all six symbols resolve without ImportError (the DTOs were relocated from
  `yascheduler.config.cloud`; the cloud subpackage facade is now the canonical path)

#### Scenario: Config facade no longer re-exports cloud config DTOs
- **WHEN** a consumer imports `from yascheduler.config import ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference`
- **THEN** ImportError is raised (the symbols moved to `yascheduler.infra.cloud`; the
  canonical import path is `from yascheduler.infra.cloud import ...`)

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.config` — shared infrastructure, may be imported by any layer above `yascheduler.shared` in the `layers` contract. SHALL NOT be imported by `yascheduler.shared` (enforced by the separate `forbidden` contract). After cloud-configs-to-infra-registry, `infra/cloud/protocols.py` no longer runtime-imports `ConfigCloud` from `yascheduler.config` (the import is intra-package to `infra/cloud/cloud_configs.py`), shrinking the outside-layer-set exemption surface by one edge. The `yascheduler.config` package remains exempt until P4 removes it entirely.
- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.client` — compat shim re-exporting `Yascheduler` from `yascheduler.entrypoints.client`; preserves the deep import path `from yascheduler.client import Yascheduler` for external downstream consumers. Not a composition root (the real client implementation now lives in `yascheduler.entrypoints.client`).

The composition root formerly at `yascheduler.di` (package root) now lives
at `yascheduler.entrypoints.di` and is therefore inside the
`yascheduler.entrypoints` layer; it is no longer in the outside-layer-set
and is subject to R3. Its imports (`yascheduler.infra`,
`yascheduler.application`, `yascheduler.domain`) flow in the layer
direction and pass the contract.

`yascheduler.shared` is the shared kernel: it SHALL contain only typing
shims (and similar cross-cutting primitives) consumed by ≥2 architectural
layers. A module whose consumers are all within a single architectural
layer belongs to that layer, not to `yascheduler.shared`. This positive
definition is the primary membership rule. As a second guardrail,
`yascheduler.shared` SHALL NOT contain business logic, domain types, or
SSH/DB/HTTP/cloud I/O — defense-in-depth beyond the layer-direction
enforcement in the `layers` contract (the `layers` contract blocks
`shared → {entrypoints, adapters, application, domain}` and the
`forbidden` contract blocks `shared → config`, but neither contract can
detect a contributor adding business logic or I/O that imports only
stdlib/third-party; the clause gives reviewers a spec-grounded basis to
reject such accretion).

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list (`yascheduler.config`, `yascheduler.data`, `yascheduler.client`) are not checked for R3 violations

#### Scenario: Composition root is layer-checked after migration
- **WHEN** the `layers` contract runs
- **THEN** `yascheduler.entrypoints.di` (a resident of the `yascheduler.entrypoints` layer) IS checked for R3 violations like any other entrypoints-layer module, and passes because its imports (`yascheduler.infra`, `yascheduler.application`, `yascheduler.domain`) flow downward through the layer direction

#### Scenario: Outside-set modules still use facades
- **WHEN** `yascheduler.entrypoints.di` imports `Task` from `yascheduler.domain`
- **THEN** it imports via `from yascheduler.domain import Task` (R2 applies)

#### Scenario: yascheduler.client shim imports via facade
- **WHEN** `yascheduler.client` (the compat shim) imports `Yascheduler`
- **THEN** it imports via `from yascheduler.entrypoints import Yascheduler` (R2 applies), not via a deep submodule path

#### Scenario: yascheduler.shared contains only cross-layer typing shims
- **WHEN** a module under `yascheduler/shared/` is inspected
- **THEN** it contains only typing shims (and similar cross-cutting primitives) consumed by ≥2 architectural layers — no domain entities, no use-case orchestration, no SSH/DB/HTTP/cloud I/O, and no module whose consumers are all within a single architectural layer

#### Scenario: Single-layer utility is rejected from yascheduler.shared
- **WHEN** a contributor proposes to add a module to `yascheduler/shared/` whose production consumers are all within one architectural layer (e.g., only `entrypoints`, or only `application`)
- **THEN** the reviewer rejects the addition and directs the contributor to place the module in the consuming layer; the positive membership rule ("≥2 architectural layers") is the primary criterion, and the "no SSH/DB/HTTP/cloud I/O" clause is the secondary guardrail

#### Scenario: Daemon launchers are layer-checked after migration
- **WHEN** the `layers` contract runs
- **THEN** `yascheduler.entrypoints.cli.daemon_systemd` and `yascheduler.entrypoints.cli.daemon_sysv` (under the `yascheduler.entrypoints` layer) ARE checked for R3 violations like any other entrypoints-layer module, and pass because their imports (`yascheduler.infra.cli.daemonize`, `yascheduler.shared` typing shims, `yascheduler.entrypoints` path constants) flow downward through the layer direction

#### Scenario: infra cloud protocols no longer imports from yascheduler.config
- **WHEN** `infra/cloud/protocols.py` is inspected for its `ConfigCloud` import
- **THEN** it is `from .cloud_configs import ConfigCloud` (intra-package), not
  `from yascheduler.config import ConfigCloud` (the outside-layer-set exemption is
  no longer needed for this edge; `yascheduler.config` remains exempt for other
  consumers until P4)