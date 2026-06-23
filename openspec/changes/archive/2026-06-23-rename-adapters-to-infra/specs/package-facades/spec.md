## MODIFIED Requirements

### Requirement: Layer direction (R3)

The system SHALL enforce the import direction
`yascheduler.infra → yascheduler.application → yascheduler.domain → yascheduler.shared`
via an `import-linter` `layers` contract configured in `pyproject.toml`.
`yascheduler.infra` may import from `yascheduler.application`,
`yascheduler.domain`, and `yascheduler.shared`. `yascheduler.application`
may import from `yascheduler.domain` and `yascheduler.shared`.
`yascheduler.domain` may import from `yascheduler.shared`.
`yascheduler.shared` SHALL NOT import from any other layer in the
project. Both direct and indirect imports are checked.

#### Scenario: Adapter imports from domain — allowed
- **WHEN** a module in `yascheduler.infra` imports a symbol from `yascheduler.domain`
- **THEN** the `layers` contract reports no violation

#### Scenario: Application imports from adapters at module level — violation
- **WHEN** a module in `yascheduler.application` imports a symbol from `yascheduler.infra` at module level (not under `TYPE_CHECKING`)
- **THEN** the `layers` contract reports a violation

#### Scenario: Domain imports from application or adapters — violation
- **WHEN** any module in `yascheduler.domain` imports from `yascheduler.application` or `yascheduler.infra`
- **THEN** the `layers` contract reports a violation

#### Scenario: Indirect imports are caught
- **WHEN** a module in `yascheduler.domain` imports a module that (transitively) imports from `yascheduler.application`
- **THEN** the `layers` contract reports a violation

#### Scenario: yascheduler.shared imports from adapters — violation
- **WHEN** any module in `yascheduler.shared` imports from `yascheduler.infra`, `yascheduler.application`, or `yascheduler.domain`
- **THEN** the `layers` contract reports a violation

### Requirement: Within-package relative imports (R1)

The system SHALL use single-level relative import syntax (`from .foo import Bar`)
for imports between sibling modules inside the same package directory.
Parent-traversal relative imports (`from .. import`, `from ... import`,
`from .... import`, etc.) SHALL NOT appear anywhere in the `yascheduler`
package tree — they obscure the dependency direction and cross package
boundaries silently. Imports that need to reach a parent or sibling
package SHALL use absolute facade paths (R2). Absolute self-references
(e.g., a module in `yascheduler.infra.cli` importing another module
in the same package via `from yascheduler.infra.cli.check_status import ...`)
SHALL NOT appear inside that package.

#### Scenario: infra/cli/__init__.py uses relative imports
- **WHEN** `yascheduler/infra/cli/__init__.py` imports its own submodules (`check_status`, `daemonize`, `init`, `manage_node`, `show_nodes`, `submit`)
- **THEN** it uses `from .check_status import check_status` style, not `from yascheduler.infra.cli.check_status import check_status`

### Requirement: Cross-package facade imports (R2)

The system SHALL import symbols from another package via that package's
`__init__.py` only. For the three architectural layers, the layer's
`__init__.py` is the sole public surface for cross-layer consumers:

- `yascheduler.infra/__init__.py` — sole entry point for `application` and composition root to consume adapter symbols (gateway, cloud provisioner, schema initializer, webhook handler, retry exceptions).
- `yascheduler.application/__init__.py` — sole entry point for `infra` and composition root to consume application symbols (unit of work, orchestrator, message bus).
- `yascheduler.domain/__init__.py` — sole entry point for `infra`, `application`, and composition root to consume domain symbols.

Subpackage facades (`yascheduler.infra.ssh`, `yascheduler.infra.cloud`,
`yascheduler.infra.persistence`, `yascheduler.infra.notifier`) are
internal organization of the `infra` layer; cross-layer consumers
SHALL NOT import from them directly. Direct imports of submodules from
outside the package bypass the public surface and SHALL NOT appear in
any import.

#### Scenario: Adapter imports Task via domain facade
- **WHEN** a module in `yascheduler.infra` is added and needs to import `Task`
- **THEN** it uses `from yascheduler.domain import Task`, not `from yascheduler.domain.model import Task`

#### Scenario: Application imports adapter symbols via adapters layer facade
- **WHEN** a module in `yascheduler.application` needs to import `SSHMachineGateway` or `CloudProvisionerImpl`
- **THEN** it uses `from yascheduler.infra import SSHMachineGateway, CloudProvisionerImpl`, not `from yascheduler.infra.ssh import SSHMachineGateway` or `from yascheduler.infra.ssh.gateway import SSHMachineGateway`

#### Scenario: Composition root imports use layer facades
- **WHEN** a module in the composition root (`di.py`, `client.py`) imports a symbol from any layer
- **THEN** the import goes through the layer's `__init__.py` (e.g. `from yascheduler.infra import webhook_handler`), not through a subpackage facade or deep submodule path

#### Scenario: Within-layer cross-subpackage imports also use the layer facade
- **WHEN** a module in `yascheduler.infra.cli` needs `SSHMachineGateway` (which lives in `yascheduler.infra.ssh`)
- **THEN** it imports via `from yascheduler.infra import SSHMachineGateway` — the layer facade is the single public surface, even for sibling subpackages within the same layer

### Requirement: Layers contract configuration

The `[tool.importlinter]` section in `pyproject.toml` SHALL be
configured with:

- `root_package = "yascheduler"`.
- `exclude_type_checking_imports = true` (imports inside `if TYPE_CHECKING:` guards are not flagged as R3 violations, since they are type-only references with no runtime dependency).
- A `layers` contract with the name `Clean architecture layers` and `layers = ["yascheduler.infra", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`.
- A `forbidden` contract with the name `Shared kernel has no config imports`, `source_modules = ["yascheduler.shared"]`, `forbidden_modules = ["yascheduler.config"]`.
- Dev dependency pinned as `import-linter >=2.5,<2.6` (the upper bound is required because `import-linter 2.6+` dropped Python 3.9 support, and the project pins `python >=3.9`). Both `layers` and `forbidden` contract types are supported in this version range.

#### Scenario: pyproject.toml contains required keys
- **WHEN** `pyproject.toml` is parsed
- **THEN** the `[tool.importlinter]` section contains `root_package`, `exclude_type_checking_imports`, one `[[tool.importlinter.contracts]]` entry of type `layers` with `yascheduler.shared` as the 4th layer, and one `[[tool.importlinter.contracts]]` entry of type `forbidden` with `source_modules = ["yascheduler.shared"]` and `forbidden_modules = ["yascheduler.config"]`

#### Scenario: TYPE_CHECKING imports not flagged
- **WHEN** a module in `yascheduler.application` contains an import under `if TYPE_CHECKING:` that references a symbol in `yascheduler.infra`
- **THEN** the `layers` contract does NOT report a violation (the import is type-only)

#### Scenario: Module-level imports still flagged
- **WHEN** a module in `yascheduler.application` contains a module-level import (not under `TYPE_CHECKING`) from `yascheduler.infra`
- **THEN** the `layers` contract reports a violation (unless covered by `ignore_imports`)

### Requirement: Documented residual edges

The layers contract SHALL include `ignore_imports` entries for two
specific module-level edges that violate R3, documented as residual
until the follow-up change `gateway-sftp-wrapping` removes them:

- `"yascheduler.application.consume_task -> yascheduler.infra"`
- `"yascheduler.application.orchestrator -> yascheduler.infra"`

These edges exist because the application code uses `backoff.on_exception(...)`
with the SSH exception tuples (`SFTPRetryExc`, `AllSSHRetryExc`), and the
gateway currently exposes a raw asyncssh `SFTPClient` via `get_sftp()` —
so gateway-side exception translation cannot reach the SFTP call sites.
Properly fixing the violations requires a gateway SFTP refactor tracked
in the follow-up change `gateway-sftp-wrapping`. These two edges are
**R2-resolved and R3-residual**: the symbols are now reached through the
`yascheduler.infra` layer facade (R2-compliant), but the
application→infra layer crossing itself remains an R3 violation that
only the follow-up change can remove.

#### Scenario: Residual edges suppressed by layers contract
- **WHEN** the `layers` contract runs against the current codebase
- **THEN** the two specific edges are not flagged as violations

### Requirement: Extended facade contents (lazy publication driven by consumers)

The following subpackage facades SHALL re-export the symbols that
external consumers already import from their deep submodules. This is
the lazy publication policy in operation: each symbol is added because
a real cross-package consumer requires it, and R2 retroactive
enforcement demands the facade form.

- **`yascheduler/infra/__init__.py`** (the infra LAYER facade — sole public surface for cross-layer consumers and composition root) SHALL re-export:
  - `SSHMachineGateway`, `AllSSHRetryExc`, `SFTPRetryExc` from `.ssh` (consumed by `yascheduler.application.*` at module level for backoff and under `TYPE_CHECKING` for type hints; also consumed within the `infra` layer by `cli.*` and `cloud.manager`).
  - `CloudProvisionerImpl` from `.cloud` (consumed by `yascheduler.application.*` under `TYPE_CHECKING` and by the composition root `yascheduler.di`).
  - `CloudAdapter` from `.cloud` (consumed by the composition root `yascheduler.di` for adapter typing).
  - `apply_schema` from `.persistence` (consumed by `infra.cli.init`).
  - `webhook_handler` from `.notifier` (consumed by the composition root `yascheduler.di`).
  - `PostgresUnitOfWork` from `.persistence` (consumed by the composition root `yascheduler.di` for UoW wiring).
- **`yascheduler/application/__init__.py`** SHALL re-export:
  - `AbstractUnitOfWork` from `.uow` (consumed by `infra.cli.manage_node`).
  - `Orchestrator` from `.orchestrator` (consumed by `infra.cli.daemonize` and the composition root `yascheduler.di`).
  - `MessageBus` from `.message_bus` (consumed by `infra.persistence.postgres_uow` and the composition root `yascheduler.di`).
  - `submit_task` from `.submit_task` (consumed by the composition root `yascheduler.di`).
- **`yascheduler/infra/notifier/__init__.py`** SHALL re-export:
  - `webhook_handler` from `.webhook` (consumed by the composition root via the `infra` layer facade).
- **`yascheduler/infra/cloud/__init__.py`** SHALL re-export:
  - `get_rnd_name` from `.utils` (consumed within the `cloud` subpackage by `providers/*`).
  - (Existing re-exports `CloudProvisionerImpl`, `CloudAdapter`, `PCloudConfig`, `get_key_name`, etc. preserved.)
- **`yascheduler/infra/persistence/__init__.py`** SHALL re-export:
  - `apply_schema` from `.postgres_schema` (consumed by `infra.cli.init` via the `infra` layer facade).
  - `PostgresUnitOfWork` from `.postgres_uow` (consumed by the composition root `yascheduler.di` via the `infra` layer facade).
  - (Preserved existing `load_query` and `UnitOfWorkNotInitializedError`.)
- **`yascheduler/config/__init__.py`** SHALL re-export:
  - `AzureImageReference` from `.cloud` (consumed by `infra.cloud.providers.az` under `TYPE_CHECKING`).

The re-exports enumerated here are the complete set required to make
every pre-existing cross-package import R2-compliant, including
composition-root (`yascheduler.di`) wiring.

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

### Requirement: Documented private-symbol carve-outs

The following deep-path imports SHALL remain (R2 carve-outs) because
the symbols are deliberately private (leading underscore) and MUST NOT
be promoted to any facade:

- `yascheduler/di.py`: `from .infra.cloud.adapters import _resolve_adapter`. `_resolve_adapter` is a private factory that the composition root wires explicitly; promoting it would leak an internal symbol to the cross-layer public surface. This is the only R2 carve-out in the codebase outside the two R3 residual edges.

#### Scenario: Private symbols stay on deep paths
- **WHEN** a leading-underscore symbol (e.g. `_resolve_adapter`) is needed by the composition root
- **THEN** it is imported via its deep path (`from .infra.cloud.adapters import _resolve_adapter`), not promoted to the `infra` layer facade

### Requirement: Broad ignore_imports tradeoff

The two `ignore_imports` entries in the `layers` contract SHALL use the
**layer facade path** (`yascheduler.application.{consume_task,orchestrator} -> yascheduler.infra`)
rather than a deep path. This is broader than a deep-path carve-out:
any future module-level `from yascheduler.infra import <anything>`
added to `consume_task.py` or `orchestrator.py` would be silently
suppressed by the same edge — not just the SSH-exception tuples the
prose justifies. The tradeoff is deliberate (matches the layer-facade
import form); reviewers MUST scrutinize any new adapter import in
those two files until the follow-up change `gateway-sftp-wrapping`
removes the residuals entirely.

#### Scenario: Reviewer scrutinizes new adapter imports in residual files
- **WHEN** a contributor adds a new module-level `from yascheduler.infra import X` to `consume_task.py` or `orchestrator.py`
- **THEN** the reviewer verifies the import is justified (same shape as the residual) or requires the contributor to fix forward
