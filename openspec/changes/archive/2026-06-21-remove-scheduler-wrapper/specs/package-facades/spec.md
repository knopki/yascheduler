## MODIFIED Requirements

### Requirement: Cross-package facade imports (R2)

The system SHALL import symbols from another package via that package's
`__init__.py` only. For the three architectural layers, the layer's
`__init__.py` is the sole public surface for cross-layer consumers:

- `yascheduler.adapters/__init__.py` — sole entry point for `application` and composition root to consume adapter symbols (gateway, cloud provisioner, schema initializer, webhook handler, retry exceptions).
- `yascheduler.application/__init__.py` — sole entry point for `adapters` and composition root to consume application symbols (unit of work, orchestrator, message bus).
- `yascheduler.domain/__init__.py` — sole entry point for `adapters`, `application`, and composition root to consume domain symbols.

Subpackage facades (`yascheduler.adapters.ssh`, `yascheduler.adapters.cloud`,
`yascheduler.adapters.persistence`, `yascheduler.adapters.notifier`) are
internal organization of the `adapters` layer; cross-layer consumers
SHALL NOT import from them directly. Direct imports of submodules from
outside the package bypass the public surface and SHALL NOT appear in
any import.

#### Scenario: Adapter imports Task via domain facade
- **WHEN** a module in `yascheduler.adapters` is added and needs to import `Task`
- **THEN** it uses `from yascheduler.domain import Task`, not `from yascheduler.domain.model import Task`

#### Scenario: Application imports adapter symbols via adapters layer facade
- **WHEN** a module in `yascheduler.application` needs to import `SSHMachineGateway` or `CloudProvisionerImpl`
- **THEN** it uses `from yascheduler.adapters import SSHMachineGateway, CloudProvisionerImpl`, not `from yascheduler.adapters.ssh import SSHMachineGateway` or `from yascheduler.adapters.ssh.gateway import SSHMachineGateway`

#### Scenario: Composition root imports use layer facades
- **WHEN** a module in the composition root (`di.py`, `client.py`) imports a symbol from any layer
- **THEN** the import goes through the layer's `__init__.py` (e.g. `from yascheduler.adapters import webhook_handler`), not through a subpackage facade or deep submodule path

#### Scenario: Within-layer cross-subpackage imports also use the layer facade
- **WHEN** a module in `yascheduler.adapters.cli` needs `SSHMachineGateway` (which lives in `yascheduler.adapters.ssh`)
- **THEN** it imports via `from yascheduler.adapters import SSHMachineGateway` — the layer facade is the single public surface, even for sibling subpackages within the same layer

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.config` — shared infrastructure, may be imported by any layer.
- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.di`, `yascheduler.client` — composition root; may import from any layer.
- `yascheduler.db` — legacy, scheduled for deletion; MUST NOT be modified by this change.
- `yascheduler.compat` — internal utility; not part of the public API.
- `yascheduler.aiida_plugin` — separate stable entry point; not part of the package's main public API.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list are not checked for R3 violations

#### Scenario: Outside-set modules still use facades
- **WHEN** `yascheduler.di` imports `Task` from `yascheduler.domain`
- **THEN** it imports via `from yascheduler.domain import Task` (R2 applies)

#### Scenario: db.py is not modified
- **WHEN** the change is implemented
- **THEN** `yascheduler/db.py` is not touched (legacy, scheduled for deletion)

### Requirement: Extended facade contents (lazy publication driven by consumers)

The following subpackage facades SHALL re-export the symbols that
external consumers already import from their deep submodules. This is
the lazy publication policy in operation: each symbol is added because
a real cross-package consumer requires it, and R2 retroactive
enforcement demands the facade form.

- **`yascheduler/adapters/__init__.py`** (the adapters LAYER facade — sole public surface for cross-layer consumers and composition root) SHALL re-export:
  - `SSHMachineGateway`, `AllSSHRetryExc`, `SFTPRetryExc` from `.ssh` (consumed by `yascheduler.application.*` at module level for backoff and under `TYPE_CHECKING` for type hints; also consumed within the `adapters` layer by `cli.*` and `cloud.manager`).
  - `CloudProvisionerImpl` from `.cloud` (consumed by `yascheduler.application.*` under `TYPE_CHECKING` and by the composition root `yascheduler.di`).
  - `CloudAdapter` from `.cloud` (consumed by the composition root `yascheduler.di` for adapter typing).
  - `apply_schema` from `.persistence` (consumed by `adapters.cli.init`).
  - `webhook_handler` from `.notifier` (consumed by the composition root `yascheduler.di`).
  - `PostgresUnitOfWork` from `.persistence` (consumed by the composition root `yascheduler.di` for UoW wiring).
- **`yascheduler/application/__init__.py`** SHALL re-export:
  - `AbstractUnitOfWork` from `.uow` (consumed by `adapters.cli.manage_node`).
  - `Orchestrator` from `.orchestrator` (consumed by `adapters.cli.daemonize` and the composition root `yascheduler.di`).
  - `MessageBus` from `.message_bus` (consumed by `adapters.persistence.postgres_uow` and the composition root `yascheduler.di`).
  - `submit_task` from `.submit_task` (consumed by the composition root `yascheduler.di`).
- **`yascheduler/adapters/notifier/__init__.py`** SHALL re-export:
  - `webhook_handler` from `.webhook` (consumed by the composition root via the `adapters` layer facade).
- **`yascheduler/adapters/cloud/__init__.py`** SHALL re-export:
  - `get_rnd_name` from `.utils` (consumed within the `cloud` subpackage by `providers/*`).
  - (Existing re-exports `CloudProvisionerImpl`, `CloudAdapter`, `PCloudConfig`, `get_key_name`, etc. preserved.)
- **`yascheduler/adapters/persistence/__init__.py`** SHALL re-export:
  - `apply_schema` from `.postgres_schema` (consumed by `adapters.cli.init` via the `adapters` layer facade).
  - `PostgresUnitOfWork` from `.postgres_uow` (consumed by the composition root `yascheduler.di` via the `adapters` layer facade).
  - (Preserved existing `load_query` and `UnitOfWorkNotInitializedError`.)
- **`yascheduler/config/__init__.py`** SHALL re-export:
  - `AzureImageReference` from `.cloud` (consumed by `adapters.cloud.providers.az` under `TYPE_CHECKING`).

The re-exports enumerated here are the complete set required to make
every pre-existing cross-package import R2-compliant, including
composition-root (`yascheduler.di`) wiring.

#### Scenario: Adapters layer facade exposes the cross-layer surface
- **WHEN** a consumer imports `from yascheduler.adapters import SSHMachineGateway, AllSSHRetryExc, SFTPRetryExc, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork`
- **THEN** all eight symbols resolve without ImportError

#### Scenario: Application facade exposes UoW, Orchestrator, MessageBus, submit_task
- **WHEN** a consumer imports `from yascheduler.application import AbstractUnitOfWork, Orchestrator, MessageBus, submit_task`
- **THEN** all four symbols resolve without ImportError

#### Scenario: Notifier subpackage facade exposes webhook_handler
- **WHEN** a consumer imports `from yascheduler.adapters.notifier import webhook_handler`
- **THEN** the symbol resolves without ImportError

#### Scenario: Cloud subpackage facade exposes get_rnd_name
- **WHEN** a consumer imports `from yascheduler.adapters.cloud import get_rnd_name`
- **THEN** the symbol resolves without ImportError

#### Scenario: Persistence subpackage facade exposes apply_schema and PostgresUnitOfWork
- **WHEN** a consumer imports `from yascheduler.adapters.persistence import apply_schema, PostgresUnitOfWork`
- **THEN** both symbols resolve without ImportError

#### Scenario: Config facade exposes AzureImageReference
- **WHEN** a consumer imports `from yascheduler.config import AzureImageReference`
- **THEN** the symbol resolves without ImportError

### Requirement: Documented private-symbol carve-outs

The following deep-path imports SHALL remain (R2 carve-outs) because
the symbols are deliberately private (leading underscore) and MUST NOT
be promoted to any facade:

- `yascheduler/di.py`: `from .adapters.cloud.adapters import _resolve_adapter`. `_resolve_adapter` is a private factory that the composition root wires explicitly; promoting it would leak an internal symbol to the cross-layer public surface. This is the only R2 carve-out in the codebase outside the two R3 residual edges.

#### Scenario: Private symbols stay on deep paths
- **WHEN** a leading-underscore symbol (e.g. `_resolve_adapter`) is needed by the composition root
- **THEN** it is imported via its deep path (`from .adapters.cloud.adapters import _resolve_adapter`), not promoted to the `adapters` layer facade
