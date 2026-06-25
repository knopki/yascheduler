## Purpose

Define the package-facade import discipline for `yascheduler`: clean-architecture layer direction (R3, enforced via `import-linter`), within-package relative imports (R1), cross-package facade imports via the layer's `__init__.py` (R2), the lazy-publication policy, outside-layer-set exemptions, residual-edge documentation, and the extended facade contents required for R2 retroactive compliance across the codebase.
## Requirements
### Requirement: Layer direction (R3)

The system SHALL enforce the import direction
`yascheduler.entrypoints → yascheduler.infra → yascheduler.application → yascheduler.domain → yascheduler.shared`
via an `import-linter` `layers` contract configured in `pyproject.toml`.

`yascheduler.entrypoints` (the outermost layer, hosting driving adapters and
the composition root) may import from `yascheduler.infra`,
`yascheduler.application`, `yascheduler.domain`, `yascheduler.shared`, and the
outside-layer-set modules (`yascheduler.config`, `yascheduler.di`, etc.).
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

#### Scenario: yascheduler.shared imports only stdlib and third-party
- **WHEN** any module in `yascheduler.shared` is inspected for its imports
- **THEN** it imports only from the standard library, third-party packages, and sibling modules within `yascheduler.shared` — never from any other `yascheduler` layer

#### Scenario: Entrypoints imports from infra — allowed
- **WHEN** a module in `yascheduler.entrypoints` imports a symbol from `yascheduler.infra` (e.g., the composition root wiring an SSH gateway)
- **THEN** the `layers` contract reports no violation

#### Scenario: Infra imports from entrypoints — violation
- **WHEN** a module in `yascheduler.infra` imports a symbol from `yascheduler.entrypoints`
- **THEN** the `layers` contract reports a violation (driven layers may not import upward into driving adapters)

#### Scenario: Application imports from entrypoints — violation
- **WHEN** a module in `yascheduler.application` imports a symbol from `yascheduler.entrypoints`
- **THEN** the `layers` contract reports a violation

### Requirement: Shared kernel config-import prohibition

The system SHALL enforce, via an `import-linter` `forbidden` contract
configured in `pyproject.toml`, that no module in `yascheduler.shared`
imports from `yascheduler.config`. This prevents an import cycle:
`yascheduler.config` already imports `yascheduler.shared.Self` (in
`config/{cloud,remote,engine_repository}.py`), so a reverse edge
`yascheduler.shared → yascheduler.config` would close a cycle.

The `forbidden` contract SHALL be configured with:
- `name = "Shared kernel has no config imports"`
- `type = "forbidden"`
- `source_modules = ["yascheduler.shared"]`
- `forbidden_modules = ["yascheduler.config"]`

Other outside-layer-set modules (`yascheduler.data`, `yascheduler.di`,
`yascheduler.client`) are NOT in `forbidden_modules`. The practical risk of
`yascheduler.shared` importing an entry point or a compat shim is
negligible; only `yascheduler.config` creates a real cycle risk because
it is a peer utility module that already depends on `yascheduler.shared`.

#### Scenario: yascheduler.shared imports from yascheduler.config — violation
- **WHEN** a module in `yascheduler.shared` imports a symbol from `yascheduler.config`
- **THEN** the `forbidden` contract reports a violation

#### Scenario: yascheduler.config imports from yascheduler.shared — allowed
- **WHEN** a module in `yascheduler.config` imports `Self` from `yascheduler.shared`
- **THEN** no contract reports a violation (the `layers` contract does not cover `config` since it is outside-layer-set; the `forbidden` contract is directional and only blocks the reverse edge)

### Requirement: Within-package relative imports (R1)

Modules within the same package (e.g. `yascheduler.infra.persistence`, `yascheduler.entrypoints.cli`) SHALL use relative imports
(`from .xxx import yyy`) for symbols from other modules in the same package.
Absolute cross-package imports
(`from yascheduler.entrypoints.cli.xxx import yyy`) of a sibling within the
same package SHALL NOT appear inside that package. This applies to
intra-package imports in `yascheduler.infra.persistence`,
`yascheduler.entrypoints.cli`, and all other subpackages.

The `yascheduler/infra/cli/` subpackage is liquidated (both `daemonize.py`
and `__init__.py` are deleted, and the directory is removed); no
`yascheduler.infra.cli` package exists, so no within-package relative-import
scenario applies to it.

#### Scenario: entrypoints/cli/__init__.py uses relative imports
- **WHEN** `yascheduler/entrypoints/cli/__init__.py` imports its own submodules
- **THEN** it uses `from .init import init` style, not `from yascheduler.entrypoints.cli.init import init`; `show_nodes` and `submit` are NOT re-exported by the facade (they are invoked by console_script, not imported across layers — same pattern as `init`)

#### Scenario: Domain modules use relative imports
- **WHEN** `yascheduler/domain/model.py` imports from another module in `yascheduler/domain/`
- **THEN** it uses `from .exceptions import ...` style, not `from yascheduler.domain.exceptions import ...`

#### Scenario: No parent-traversal relative imports anywhere
- **WHEN** any `.py` file under `yascheduler/` is inspected
- **THEN** no `from .. import`, `from ... import`, `from .... import` (or deeper) relative imports appear — only `from .` (single-level sibling) relative imports are permitted

#### Scenario: infra/cli/ does not exist
- **WHEN** the `yascheduler/infra/cli/` directory is inspected
- **THEN** it does not exist; the `daemonize` module has moved to `yascheduler/entrypoints/cli/daemonize.py` and the empty `infra/cli/` subpackage has been removed

### Requirement: Cross-package facade imports (R2)

The system SHALL import symbols from another package via that package's
`__init__.py` only. For the three architectural layers, the layer's
`__init__.py` is the sole public surface for cross-layer consumers:

- `yascheduler.infra/__init__.py` — sole entry point for `application` and composition root to consume adapter symbols (gateway, cloud provisioner, schema initializer, webhook handler, retry exceptions).
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

#### Scenario: Application imports adapter symbols via adapters layer facade
- **WHEN** a module in `yascheduler.application` needs to import `SSHMachineGateway` or `CloudProvisionerImpl`
- **THEN** it uses `from yascheduler.infra import SSHMachineGateway, CloudProvisionerImpl`, not `from yascheduler.infra.ssh import SSHMachineGateway` or `from yascheduler.infra.ssh.gateway import SSHMachineGateway`

#### Scenario: Composition root imports use layer facades
- **WHEN** a module in the composition root (`di.py`, `client.py`) imports a symbol from any layer
- **THEN** the import goes through the layer's `__init__.py` (e.g. `from yascheduler.infra import webhook_handler`), not through a subpackage facade or deep submodule path

#### Scenario: Within-layer cross-subpackage imports also use the layer facade
- **WHEN** a module in `yascheduler.infra.cli` needs `SSHMachineGateway` (which lives in `yascheduler.infra.ssh`)
- **THEN** it imports via `from yascheduler.infra import SSHMachineGateway` — the layer facade is the single public surface, even for sibling subpackages within the same layer

### Requirement: Package facade as public surface (lazy publication)

Each subpackage of `yascheduler` SHALL designate its `__init__.py` as
the only public surface. Symbols are added to the facade lazily —
only when an external consumer actually needs them. Empty facades
(no symbols re-exported yet) are valid and represent "no public
surface yet". Adding a symbol to a facade is a deliberate act, not
an automatic re-export of all non-underscore names.

#### Scenario: Empty facade is valid
- **WHEN** a subpackage's `__init__.py` is empty of public re-exports because no external consumer needs any of its symbols
- **THEN** the empty facade is the valid public surface for that subpackage

#### Scenario: Symbol added when consumer needs it
- **WHEN** an adapter needs `submit_task` from `yascheduler.application`
- **THEN** `yascheduler/application/__init__.py` is updated to re-export `submit_task` from its defining submodule, and the adapter imports it via `from yascheduler.application import submit_task`

### Requirement: Entrypoints layer facade

The `yascheduler/entrypoints/__init__.py` module SHALL be the layer facade for
the `entrypoints` layer (the outermost hexagonal layer hosting driving adapters
and the composition root). It SHALL re-export `Yascheduler` from
`.client` as the sole public surface of the layer, mirroring the layer-facade
convention used by `yascheduler/infra/__init__.py` (`M-ADAPTERS`) and
`yascheduler/application/__init__.py` (`M-APPLICATION`).

`yascheduler/entrypoints/__init__.py` SHALL be the only public surface through
which cross-layer consumers import symbols from the `entrypoints` layer; direct
imports of `yascheduler.entrypoints.client` from outside the layer SHALL NOT
appear in application, domain, infra, shared, or config modules (they are below
`entrypoints` in the layer direction and may not import upward).

Symbols are added to the `entrypoints` facade lazily — only when an external
consumer actually needs them. The `AiiDA` scheduler plugin
(`entrypoints/aiida_plugin.py`) is NOT re-exported by the facade: it is
discovered via the `[project.entry-points."aiida.schedulers"]` registry, not via
`from yascheduler.entrypoints import …`. The daemon launchers
(`entrypoints/cli/daemon_systemd.py` and
`entrypoints/cli/daemon_sysv.py`) are NOT re-exported by the facade either:
they are invoked by path from the systemd unit file and SysV init.d script
templates (via `%YASCHEDULER_DAEMON_FILE%` substitution produced by `yainit`),
not imported across layers. The `daemonize` entry point
(`entrypoints/cli/daemonize.py`) is likewise NOT re-exported by the facade: it
is invoked by the `yascheduler` console_script, not imported across layers.
With `infra/cli/` liquidated, no deferred `infra/cli/*` migration remains.

#### Scenario: Entrypoints facade re-exports Yascheduler
- **WHEN** a consumer imports `from yascheduler.entrypoints import Yascheduler`
- **THEN** the symbol resolves without ImportError

#### Scenario: Entrypoints facade is the sole public surface
- **WHEN** a module in `yascheduler.application`, `yascheduler.domain`, `yascheduler.infra`, `yascheduler.shared`, or `yascheduler.config` imports a symbol from `yascheduler.entrypoints`
- **THEN** the import goes through `yascheduler.entrypoints.__init__`, not a deep submodule path like `yascheduler.entrypoints.client`

#### Scenario: AiiDA plugin is not re-exported by the entrypoints facade
- **WHEN** the `entrypoints/__init__.py` facade is inspected
- **THEN** it re-exports only `Yascheduler`; `YaScheduler` and `YaschedJobResource` from `aiida_plugin.py` are NOT re-exported (plugin discovery is via the entry-point registry, not the facade)

#### Scenario: Daemon launchers are not re-exported by the entrypoints facade
- **WHEN** the `entrypoints/__init__.py` facade is inspected
- **THEN** it re-exports only `Yascheduler`; `start_daemon` (from `entrypoints/cli/daemon_sysv.py`), `daemonize` (from `entrypoints/cli/daemonize.py`), and the `__main__` blocks of both `entrypoints/cli/daemon_systemd.py` and `entrypoints/cli/daemon_sysv.py` are NOT re-exported (the launchers are invoked by path from service templates or by the `yascheduler` console_script, not imported across layers)

#### Scenario: No deferred infra/cli migration remains
- **WHEN** the `entrypoints/__init__.py` change summary is inspected
- **THEN** it no longer mentions `infra/cli/` as a deferred follow-up; the migration is complete

### Requirement: Compat shim for yascheduler.client

The file `yascheduler/client.py` SHALL be retained as a thin compatibility
shim that re-exports `Yascheduler` from `yascheduler.entrypoints.client`. This
preserves the deep import path `from yascheduler.client import Yascheduler`
for external downstream consumers.

The shim SHALL:
- Re-export exactly the public symbol `Yascheduler` (no `Config`, no internal
  helpers).
- Declare `__all__ = ["Yascheduler"]`.
- Carry a full GRACE-lite `MODULE_CONTRACT` whose `PURPOSE` states that the
  real implementation lives in `yascheduler/entrypoints/client.py`.

The shim SHALL NOT:
- Re-export `Config` or any other symbol used only by tests (test patches must
  target `yascheduler.entrypoints.client.Config…`, the real module).
- Contain any business logic or duplication of `entrypoints/client.py`.

`yascheduler.client` is reclassified in the outside-layer-set exemption list
from "composition root" to "compat shim"; it remains outside the `layers`
contract and is not checked for R3 layer direction.

#### Scenario: Deep import path resolves for external consumers
- **WHEN** an external downstream consumer imports `from yascheduler.client import Yascheduler`
- **THEN** the symbol resolves without `ModuleNotFoundError` (the physical shim file registers `yascheduler.client` in `sys.modules`)

#### Scenario: Package-root import resolves
- **WHEN** an external downstream consumer imports `from yascheduler import Yascheduler`
- **THEN** the symbol resolves without ImportError (re-exported via `yascheduler/__init__.py` from `yascheduler.entrypoints`)

#### Scenario: Shim does not re-export Config
- **WHEN** a test attempts `patch("yascheduler.client.Config.from_config_parser")`
- **THEN** the patch raises `AttributeError` because `Config` is not re-exported by the shim; the test must target `yascheduler.entrypoints.client.Config.from_config_parser` instead

#### Scenario: Shim carries GRACE-lite contract
- **WHEN** `yascheduler/client.py` is inspected
- **THEN** it contains a full `START_MODULE_CONTRACT … END_MODULE_CONTRACT` block whose `PURPOSE` identifies it as a compat shim and points to `yascheduler/entrypoints/client.py` as the real implementation

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.config` — shared infrastructure, may be imported by any layer above `yascheduler.shared` in the `layers` contract. SHALL NOT be imported by `yascheduler.shared` (enforced by the separate `forbidden` contract).
- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.di` — composition root; may import from any layer. (Scheduled for migration into `yascheduler.entrypoints` in a follow-up change; remains at the package root in the interim.)
- `yascheduler.client` — compat shim re-exporting `Yascheduler` from `yascheduler.entrypoints.client`; preserves the deep import path `from yascheduler.client import Yascheduler` for external downstream consumers. Not a composition root (the real client implementation now lives in `yascheduler.entrypoints.client`).

`yascheduler.shared` SHALL NOT contain business logic, domain types, or I/O. This clause is defense-in-depth beyond the layer-direction enforcement in the `layers` contract: the `layers` contract blocks `shared → {entrypoints, adapters, application, domain}` and the `forbidden` contract blocks `shared → config`, but neither contract can detect a contributor adding business logic or I/O that imports only stdlib/third-party. The clause gives reviewers a spec-grounded basis to reject such accretion.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list (`yascheduler.config`, `yascheduler.data`, `yascheduler.di`, `yascheduler.client`) are not checked for R3 violations

#### Scenario: Outside-set modules still use facades
- **WHEN** `yascheduler.di` imports `Task` from `yascheduler.domain`
- **THEN** it imports via `from yascheduler.domain import Task` (R2 applies)

#### Scenario: yascheduler.client shim imports via facade
- **WHEN** `yascheduler.client` (the compat shim) imports `Yascheduler`
- **THEN** it imports via `from yascheduler.entrypoints import Yascheduler` (R2 applies), not via a deep submodule path

#### Scenario: yascheduler.shared contains no business logic or I/O
- **WHEN** a module under `yascheduler/shared/` is inspected
- **THEN** it contains only typing shims, pure runtime helpers, or process-global constants — no domain entities, no use-case orchestration, no SSH/DB/HTTP/cloud I/O

#### Scenario: Daemon launchers are layer-checked after migration
- **WHEN** the `layers` contract runs
- **THEN** `yascheduler.entrypoints.cli.daemon_systemd` and `yascheduler.entrypoints.cli.daemon_sysv` (under the `yascheduler.entrypoints` layer) ARE checked for R3 violations like any other entrypoints-layer module, and pass because their imports (`yascheduler.infra.cli.daemonize`, `yascheduler.shared` constants) flow downward through the layer direction

### Requirement: Layers contract configuration

The `[tool.importlinter]` section in `pyproject.toml` SHALL be
configured with:

- `root_package = "yascheduler"`.
- `exclude_type_checking_imports = true` (imports inside `if TYPE_CHECKING:` guards are not flagged as R3 violations, since they are type-only references with no runtime dependency).
- A `layers` contract with the name `Clean architecture layers` and `layers = ["yascheduler.entrypoints", "yascheduler.infra", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`.
- A `forbidden` contract with the name `Shared kernel has no config imports`, `source_modules = ["yascheduler.shared"]`, `forbidden_modules = ["yascheduler.config"]`.
- Dev dependency pinned as `import-linter >=2.5,<2.6` (the upper bound is required because `import-linter 2.6+` dropped Python 3.9 support, and the project pins `python >=3.9`). Both `layers` and `forbidden` contract types are supported in this version range.

#### Scenario: pyproject.toml contains required keys
- **WHEN** `pyproject.toml` is parsed
- **THEN** the `[tool.importlinter]` section contains `root_package`, `exclude_type_checking_imports`, one `[[tool.importlinter.contracts]]` entry of type `layers` with `yascheduler.entrypoints` as the 1st layer and `yascheduler.shared` as the 5th layer, and one `[[tool.importlinter.contracts]]` entry of type `forbidden` with `source_modules = ["yascheduler.shared"]` and `forbidden_modules = ["yascheduler.config"]`

#### Scenario: TYPE_CHECKING imports not flagged
- **WHEN** a module in `yascheduler.application` contains an import under `if TYPE_CHECKING:` that references a symbol in `yascheduler.infra`
- **THEN** the `layers` contract does NOT report a violation (the import is type-only)

#### Scenario: Module-level imports still flagged
- **WHEN** a module in `yascheduler.application` contains a module-level import (not under `TYPE_CHECKING`) from `yascheduler.infra`
- **THEN** the `layers` contract reports a violation (unless covered by `ignore_imports`)

#### Scenario: import-linter version compatible with Python 3.9
- **WHEN** the dev environment installs with `python >=3.9`
- **THEN** `import-linter >=2.5,<2.6` is installed and `lint-imports` runs without Python-version errors, and both `layers` and `forbidden` contract types are recognized

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
application→adapters layer crossing itself remains an R3 violation that
only the follow-up change can remove.

#### Scenario: Residual edges suppressed by layers contract
- **WHEN** the `layers` contract runs against the current codebase
- **THEN** the two specific edges are not flagged as violations

#### Scenario: Residual edges removed by follow-up change
- **WHEN** the follow-up change `gateway-sftp-wrapping` lands (gateway wraps SFTP operations and raises `RetryableOperationError`, application backoff retries on the domain exception)
- **THEN** the two `ignore_imports` entries are removed from the contract

#### Scenario: No new ignore_imports entries
- **WHEN** a new R3 violation is discovered during implementation
- **THEN** the violation is NOT silently added to `ignore_imports`; either it is fixed forward, or (if same shape as the residual) it is added with a matching follow-up note in the spec

### Requirement: Domain package facade contents

`yascheduler/domain/__init__.py` SHALL re-export the following
categories of symbols as the public surface of the domain layer:

- **Events** (already exported today; no regression): `DomainEvent`, `Event`, `TaskAbandoned`, `TaskAllocated`, `TaskCompleted`, `TaskCreated`, `TaskFailed`.
- **Model**: `Task` and related domain entities defined in `yascheduler.domain.model`.
- **Exceptions**: the existing `DomainError` tree from `yascheduler.domain.exceptions` (no new symbols added by this change).
- **Ports**: `TaskRepository`, `NodeRepository`, `MachineGateway`, `CloudProvisioner` Protocols from `yascheduler.domain.ports`.

#### Scenario: Domain facade exposes all required categories
- **WHEN** a consumer imports `from yascheduler.domain import Task, TaskCreated, DomainError, TaskRepository, NodeRepository, MachineGateway, CloudProvisioner`
- **THEN** all symbols resolve without ImportError

#### Scenario: Domain exception tree unchanged
- **WHEN** the existing `DomainError` tree in `yascheduler/domain/exceptions.py` is inspected after the change
- **THEN** no new exception classes are added by this change (existing hierarchy preserved)

#### Scenario: Events regression check
- **WHEN** a consumer imports the events previously available via `yascheduler.domain.__init__`
- **THEN** all event symbols still resolve

### Requirement: Extended facade contents (lazy publication driven by consumers)

The following subpackage facades SHALL re-export the symbols that
external consumers already import from their deep submodules. This is
the lazy publication policy in operation: each symbol is added because
a real cross-package consumer requires it, and R2 retroactive
enforcement demands the facade form.

- **`yascheduler/infra/__init__.py`** (the adapters LAYER facade — sole public surface for cross-layer consumers and composition root) SHALL re-export:
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
- **`yascheduler/infra/notifier/__init__.py`** SHALL re-export:
  - `webhook_handler` from `.webhook` (consumed by the composition root via the `adapters` layer facade).
- **`yascheduler/infra/cloud/__init__.py`** SHALL re-export:
  - `get_rnd_name` from `.utils` (consumed within the `cloud` subpackage by `providers/*`).
  - (Existing re-exports `CloudProvisionerImpl`, `CloudAdapter`, `PCloudConfig`, `get_key_name`, etc. preserved.)
- **`yascheduler/infra/persistence/__init__.py`** SHALL re-export:
  - `apply_schema` from `.postgres_schema` (consumed by `adapters.cli.init` via the `adapters` layer facade).
  - `PostgresUnitOfWork` from `.postgres_uow` (consumed by the composition root `yascheduler.di` via the `adapters` layer facade).
  - (Preserved existing `load_query` and `UnitOfWorkNotInitializedError`.)
- **`yascheduler/config/__init__.py`** SHALL re-export:
  - `AzureImageReference` from `.cloud` (consumed by `adapters.cloud.providers.az` under `TYPE_CHECKING`).

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

- `yascheduler/di.py`: `from .adapters.cloud.adapters import _resolve_adapter`. `_resolve_adapter` is a private factory that the composition root wires explicitly; promoting it would leak an internal symbol to the cross-layer public surface. This is the only R2 carve-out in the codebase outside the two R3 residual edges.

#### Scenario: Private symbols stay on deep paths
- **WHEN** a leading-underscore symbol (e.g. `_resolve_adapter`) is needed by the composition root
- **THEN** it is imported via its deep path (`from .adapters.cloud.adapters import _resolve_adapter`), not promoted to the `adapters` layer facade

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

### Requirement: Public API stability

The system SHALL preserve the existing public API surface of the
`yascheduler` package across changes. Public API is defined as: exported
symbols resolvable via `from yascheduler import <name>`, constructor and
method signatures (parameter positions and names, return shapes), and
documented behavior. The public contract is keyed on the resolvable symbol
(`from yascheduler import Yascheduler`), NOT on the file path that
defines it; implementation modules may be relocated inside the package
tree as long as the public re-export path continues to resolve.

Backward-compatible extensions (adding keyword-only optional parameters,
refining internal implementation, adding new public symbols) are
permitted; breaking changes (removing or repositioning parameters,
changing return shapes, removing exported symbols) SHALL be treated as a
new capability requiring explicit spec coverage.

- `yascheduler/__init__.py` exports (`Yascheduler`, `CONFIG_FILE`,
  `LOG_FILE`, `PID_FILE`, `__version__`) SHALL remain resolvable. The
  path constants (`CONFIG_FILE`, `LOG_FILE`, `PID_FILE`) SHALL be
  re-exported through `yascheduler.shared.variables` — downstream
  consumers continue to import them via `from yascheduler import
  CONFIG_FILE` with no change. `Yascheduler` SHALL be re-exported via
  `yascheduler.entrypoints` (i.e., `yascheduler/__init__.py` does
  `from .entrypoints import Yascheduler`).
- The deep import path `from yascheduler.client import Yascheduler` SHALL
  remain resolvable via the compat shim file `yascheduler/client.py`
  (which re-exports `Yascheduler` from `yascheduler.entrypoints.client`).
  The shim re-exports exactly `Yascheduler` (`__all__ = ["Yascheduler"]`);
  it does NOT re-export `Config` or other internal symbols.
- The AiiDA scheduler entrypoint SHALL remain registered under the
  entry-point *name* `yascheduler` in the
  `[project.entry-points."aiida.schedulers"]` group of `pyproject.toml`,
  pointing at the object path
  `yascheduler.entrypoints.aiida_plugin:YaScheduler`. AiiDA discovers
  plugins by entry-point name via `importlib.metadata.entry_points`, so
  the module relocation is transparent to `verdi` / `reentry scan` users.
  The deep import path `from yascheduler.aiida_plugin import …` is NOT
  preserved (no compat shim); the old module path ceases to exist. This
  is a **BREAKING** change for downstream code that pinned the deep
  module path (no such caller is known).
- `yascheduler.client` (the compat shim) SHALL preserve the `Yascheduler`
  class's public constructor and method signatures: zero-arg and
  positional callsites remain valid; keyword-only optional parameters
  may be added (e.g., for test injection); internal implementation may
  change without notice. The `to_sync` function SHALL NOT be defined in
  `yascheduler.client`; it is relocated to
  `yascheduler.shared.async_utils` and re-exported via the
  `yascheduler.shared` facade.

#### Scenario: Yascheduler symbol resolves with backward-compatible signature
- **WHEN** a downstream consumer imports `from yascheduler import Yascheduler`
- **THEN** the symbol resolves and the zero-arg constructor `Yascheduler()` and the positional constructors `Yascheduler(config_path)` / `Yascheduler(config_path, logger)` remain valid

#### Scenario: Deep import path resolves via compat shim
- **WHEN** a downstream consumer imports `from yascheduler.client import Yascheduler`
- **THEN** the symbol resolves without ImportError via the `yascheduler/client.py` shim file (which re-exports from `yascheduler.entrypoints.client`)

#### Scenario: Backward-compatible constructor extension permitted
- **WHEN** a change adds a keyword-only optional parameter to `Yascheduler.__init__` (e.g., `deps_factory` for test injection)
- **THEN** existing callsites `Yascheduler()`, `Yascheduler(config_path)`, `Yascheduler(config_path, logger)` remain valid without modification

#### Scenario: AiiDA plugin still loads under its entry-point name
- **WHEN** the AiiDA scheduler plugin is discovered via `importlib.metadata.entry_points(group="aiida.schedulers")`
- **THEN** the entry-point named `yascheduler` resolves to the object path `yascheduler.entrypoints.aiida_plugin:YaScheduler` and the class loads and behaves identically to before the relocation

#### Scenario: Old aiida_plugin module path is gone
- **WHEN** a downstream consumer attempts `from yascheduler.aiida_plugin import YaScheduler`
- **THEN** `ModuleNotFoundError` is raised (no compat shim; the old module path ceases to exist)

#### Scenario: Path constants remain resolvable from package root
- **WHEN** a downstream consumer imports `from yascheduler import CONFIG_FILE, LOG_FILE, PID_FILE`
- **THEN** all three symbols resolve without ImportError (re-exported via `yascheduler.shared.variables`)

#### Scenario: to_sync relocated to yascheduler.shared
- **WHEN** a consumer needs the `to_sync` decorator
- **THEN** it imports `from yascheduler.shared import to_sync`; the symbol is not defined in `yascheduler.client` (the shim) nor in `yascheduler.entrypoints.client` beyond its existing re-export from `yascheduler.shared`

#### Scenario: compat.py old path removed
- **WHEN** `yascheduler/compat.py` is inspected
- **THEN** the file does not exist; `Self` and `ParamSpec` are importable only via `from yascheduler.shared import Self, ParamSpec`

### Requirement: Yascheduler client query method public contract

The `Yascheduler` class SHALL preserve its public query API across the
relocation from `yascheduler/client.py` to
`yascheduler/entrypoints/client.py`. The class is defined in
`yascheduler/entrypoints/client.py` and re-exported via
`from yascheduler import Yascheduler` (package facade) and
`from yascheduler.client import Yascheduler` (compat shim); the public
contract is keyed on the resolvable symbol, not the file path.

- `Yascheduler()` zero-arg construction SHALL remain valid.
- `Yascheduler(config_path, logger)` positional callsites SHALL remain valid.
- `Yascheduler(config_path, logger, *, deps_factory=None)` SHALL add
  `deps_factory` as a keyword-only optional parameter (lazy default
  `make_cli_deps`), used as a test-injection seam.
- `queue_get_tasks(jobs, status)`, `queue_get_tasks_async(jobs, status)`,
  `queue_get_task(task_id)`, and `queue_get_task_async(task_id)` signatures
  SHALL NOT change.
- Each query method SHALL return Mappings (a `Sequence[Mapping]` for the
  list variants `queue_get_tasks` / `queue_get_tasks_async`, an
  `Optional[Mapping]` for the single-task variants `queue_get_task` /
  `queue_get_task_async`) with EXACTLY the keys
  `{task_id, label, ip, status, metadata, cloud}`.
- `status` SHALL be a `domain.TaskStatus` enum member (preserves `.name`
  access and cross-class IntEnum equality; NOT a plain `int`).
- `cloud` SHALL be `None` in the query method output (no facade path
  populates it).
- `ip` SHALL be `allocated_ip or ""` (empty string when the task has no
  allocated node).

The public contract is keyed on the resolvable symbol and applies
identically whether `Yascheduler` is imported via the package facade
(`from yascheduler import Yascheduler`), the entrypoints layer facade
(`from yascheduler.entrypoints import Yascheduler`), or the compat shim
(`from yascheduler.client import Yascheduler`).

#### Scenario: Zero-arg construction remains valid
- **WHEN** `Yascheduler()` is called with no arguments
- **THEN** the client is constructed successfully and `queue_get_tasks_async` is invokable

#### Scenario: deps_factory is keyword-only
- **WHEN** `Yascheduler(config_path, logger, my_factory)` is called with `deps_factory` positionally
- **THEN** a `TypeError` is raised

#### Scenario: Query returns six-key dict shape
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a non-empty result
- **THEN** each Mapping has exactly the keys `{task_id, label, ip, status, metadata, cloud}` and no others

#### Scenario: Status field is a domain.TaskStatus member
- **WHEN** a returned Mapping's `status` value is inspected
- **THEN** it is an instance of `yascheduler.domain.TaskStatus` (not a plain `int`), with `.name` and `.value` matching the underlying IntEnum values 0/1/2

#### Scenario: cloud is always None
- **WHEN** any query method returns a Mapping
- **THEN** the `cloud` key is present and its value is `None`

#### Scenario: ip is empty string when task unallocated
- **WHEN** a Task with `allocated_ip=None` is returned by a query method
- **THEN** the Mapping's `ip` value is `""` (empty string)

#### Scenario: Contract holds via each import path
- **WHEN** `Yascheduler` is imported via `from yascheduler import Yascheduler`, `from yascheduler.entrypoints import Yascheduler`, or `from yascheduler.client import Yascheduler`
- **THEN** all query-method scenarios above hold identically (the import path does not affect the public contract)

