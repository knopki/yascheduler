## Purpose

Define the package-facade import discipline for `yascheduler`: clean-architecture layer direction (R3, enforced via `import-linter`), within-package relative imports (R1), cross-package facade imports via the layer's `__init__.py` (R2), the lazy-publication policy, outside-layer-set exemptions, residual-edge documentation, and the extended facade contents required for R2 retroactive compliance across the codebase.
## Requirements
### Requirement: Layer direction (R3)

The system SHALL enforce the import direction
`yascheduler.entrypoints → yascheduler.infra → yascheduler.application → yascheduler.domain → yascheduler.shared`
via an `import-linter` `layers` contract configured in `pyproject.toml`.

`yascheduler.entrypoints` (the outermost layer, hosting driving adapters and
the composition root at `yascheduler.entrypoints.di`) may import from
`yascheduler.infra`, `yascheduler.application`, `yascheduler.domain`,
`yascheduler.shared`, and the outside-layer-set modules
(`yascheduler.data`, etc.). The composition root
`yascheduler.entrypoints.di` is a resident of this layer and is subject to
this R3 contract; its imports flow `entrypoints → infra → application →
domain`, which is layer-legal. `yascheduler.infra` may import from
`yascheduler.application`, `yascheduler.domain`, and `yascheduler.shared`.
`yascheduler.application` may import from `yascheduler.domain` and
`yascheduler.shared`. `yascheduler.domain` may import from
`yascheduler.shared`. `yascheduler.shared` SHALL NOT import from any other
layer in the project. Both direct and indirect imports are checked.

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

#### Scenario: Composition root imports from infra — allowed
- **WHEN** `yascheduler.entrypoints.di` imports `PostgresUnitOfWork`, `SSHMachineRepository`, `SSHMachineOperations`, `CloudProvisionerImpl`, `resolve_adapter`, and `webhook_handler` from `yascheduler.infra`
- **THEN** the `layers` contract reports no violation (composition root is a resident of `yascheduler.entrypoints` and its imports flow in the layer direction)

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

#### Scenario: Application imports adapter symbols via infra layer facade
- **WHEN** a module in `yascheduler.application` needs to import `SSHMachineRepository`, `SSHMachineOperations`, or `CloudProvisionerImpl`
- **THEN** it uses `from yascheduler.infra import SSHMachineRepository, SSHMachineOperations, CloudProvisionerImpl`, not `from yascheduler.infra.ssh import SSHMachineRepository` or `from yascheduler.infra.ssh.repository import SSHMachineRepository`

#### Scenario: Composition root imports use layer facades
- **WHEN** a module in the composition root (`entrypoints/di.py`, `entrypoints/client.py`) imports a symbol from any layer
- **THEN** the import goes through the layer's `__init__.py` (e.g. `from yascheduler.infra import webhook_handler`), not through a subpackage facade or deep submodule path

#### Scenario: Within-layer cross-subpackage imports also use the layer facade
- **WHEN** a module in `yascheduler.infra.cli` needs `SSHMachineRepository` (which lives in `yascheduler.infra.ssh`)
- **THEN** it imports via `from yascheduler.infra import SSHMachineRepository` — the layer facade is the single public surface, even for sibling subpackages within the same layer

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
and the composition root). It SHALL re-export the following symbols from its
residents as the public surface of the layer, mirroring the layer-facade
convention used by `yascheduler/infra/__init__.py` (`M-ADAPTERS`) and
`yascheduler/application/__init__.py` (`M-APPLICATION`):

- `Yascheduler` from `.client` (the public API class).
- `make_daemon` from `.di` (consumed by `yascheduler.entrypoints.cli.daemon_common`
  via the facade).
- `make_cli_deps` from `.di` (consumed by `yascheduler.entrypoints.cli.{submit,check_status,show_nodes,manage_node}`
  via the facade).
- `CLIDeps` from `.di` (consumed by `yascheduler.entrypoints.cli.{check_status,manage_node}`
  for type annotations, and by `yascheduler.entrypoints.client` which imports
  it sibling-relative as `from .di import CLIDeps`).
- `CONFIG_FILE` from `.paths` (consumed by `yascheduler.entrypoints.cli.{args,init}`
  via the facade, and by `yascheduler.entrypoints.client` sibling-relative as
  `from .paths import CONFIG_FILE`).
- `LOG_FILE` from `.paths` (consumed by `yascheduler.entrypoints.cli.daemon_sysv`
  via the facade).
- `PID_FILE` from `.paths` (consumed by `yascheduler.entrypoints.cli.daemon_sysv`
  via the facade).

`yascheduler/entrypoints/__init__.py` SHALL be the only public surface through
which cross-layer consumers import symbols from the `entrypoints` layer; direct
imports of `yascheduler.entrypoints.client` from outside the layer SHALL NOT
appear in application, domain, infra, shared, or config modules (they are below
`entrypoints` in the layer direction and may not import upward).

Symbols are added to the `entrypoints` facade lazily — only when an external
or subpackage consumer actually needs them. The `AiiDA` scheduler plugin
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
With `di.py` relocated into `entrypoints/` and `infra/cli/` liquidated, no
deferred migration remains for the entrypoints layer.

The composition root `yascheduler.entrypoints.di` itself SHALL import
`Orchestrator`, `submit_task`, `AbstractUnitOfWork`, `MessageBus`,
`AllocationTracker` from `yascheduler.application`; `TaskCreated`,
`TaskAllocated`, `TaskCompleted`, `TaskFailed`, `TaskAbandoned` from
`yascheduler.domain`; and `CloudProvisionerImpl`, `CloudAdapter`,
`SSHMachineRepository`, `SSHMachineOperations`, `PostgresUnitOfWork`, `resolve_adapter`,
`webhook_handler` from `yascheduler.infra` — all via layer facades (R2).

#### Scenario: Entrypoints facade re-exports Yascheduler, composition root, and path constants
- **WHEN** a consumer imports `from yascheduler.entrypoints import Yascheduler, make_daemon, make_cli_deps, CLIDeps, CONFIG_FILE, LOG_FILE, PID_FILE`
- **THEN** all seven symbols resolve without ImportError

#### Scenario: Entrypoints facade is the sole public surface
- **WHEN** a module in `yascheduler.application`, `yascheduler.domain`, `yascheduler.infra`, or `yascheduler.shared` imports a symbol from `yascheduler.entrypoints`
- **THEN** the import goes through `yascheduler.entrypoints.__init__`, not a deep submodule path like `yascheduler.entrypoints.client`

#### Scenario: AiiDA plugin is not re-exported by the entrypoints facade
- **WHEN** the `entrypoints/__init__.py` facade is inspected
- **THEN** it re-exports `Yascheduler`, `make_daemon`, `make_cli_deps`, `CLIDeps`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`; `YaScheduler` and `YaschedJobResource` from `aiida_plugin.py` are NOT re-exported (plugin discovery is via the entry-point registry, not the facade)

#### Scenario: Daemon launchers are not re-exported by the entrypoints facade
- **WHEN** the `entrypoints/__init__.py` facade is inspected
- **THEN** `start_daemon` (from `entrypoints/cli/daemon_sysv.py`), `daemonize` (from `entrypoints/cli/daemonize.py`), and the `__main__` blocks of both `entrypoints/cli/daemon_systemd.py` and `entrypoints/cli/daemon_sysv.py` are NOT re-exported (the launchers are invoked by path from service templates or by the `yascheduler` console_script, not imported across layers)

#### Scenario: No deferred entrypoints migration remains
- **WHEN** the `entrypoints/__init__.py` change summary is inspected
- **THEN** it no longer mentions `infra/cli/` or `di.py` as a deferred follow-up; both migrations are complete

#### Scenario: CLI subpackage imports composition root via facade
- **WHEN** `yascheduler.entrypoints.cli.daemon_common` needs `make_daemon`
- **THEN** it imports `from yascheduler.entrypoints import make_daemon` (R2 via facade), not `from ..di import make_daemon` (deep sibling-cross-subpackage)

#### Scenario: CLI subpackage imports path constants via facade
- **WHEN** `yascheduler.entrypoints.cli.args` needs `CONFIG_FILE`
- **THEN** it imports `from yascheduler.entrypoints import CONFIG_FILE` (R2 via facade), not `from ..paths import CONFIG_FILE` (deep sibling-cross-subpackage)

#### Scenario: Client sibling import of CLIDeps and path constants
- **WHEN** `yascheduler.entrypoints.client` needs `CLIDeps`, `make_cli_deps`, and `CONFIG_FILE`
- **THEN** it imports `from .di import CLIDeps, make_cli_deps` and `from .paths import CONFIG_FILE` (R1 sibling-relative, all residents of the flat `entrypoints` package)

#### Scenario: Composition root imports via layer facades
- **WHEN** `yascheduler.entrypoints.di` imports `Orchestrator` and `submit_task`
- **THEN** it imports `from yascheduler.application import Orchestrator, submit_task` (R2 via the `application` layer facade), not via a deep submodule path

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

- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.client` — compat shim re-exporting `Yascheduler` from
  `yascheduler.entrypoints.client`; preserves the deep import path
  `from yascheduler.client import Yascheduler` for external downstream
  consumers.

The composition root `yascheduler.entrypoints.di` is a resident of the
`yascheduler.entrypoints` layer and is subject to R3; its imports
(`yascheduler.infra`, `yascheduler.application`, `yascheduler.domain`) flow in
the layer direction and pass the contract.

`yascheduler.shared` is the shared kernel: it SHALL contain only typing
shims (and similar cross-cutting primitives) consumed by ≥2 architectural
layers. A module whose consumers are all within a single architectural
layer belongs to that layer, not to `yascheduler.shared`. As a second guardrail,
`yascheduler.shared` SHALL NOT contain business logic, domain types, or
SSH/DB/HTTP/cloud I/O — defense-in-depth beyond the `layers` contract.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list (`yascheduler.data`, `yascheduler.client`) are not checked for R3 violations

#### Scenario: Composition root is layer-checked
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

#### Scenario: Daemon launchers are layer-checked
- **WHEN** the `layers` contract runs
- **THEN** `yascheduler.entrypoints.cli.daemon_systemd` and `yascheduler.entrypoints.cli.daemon_sysv` (under the `yascheduler.entrypoints` layer) ARE checked for R3 violations like any other entrypoints-layer module, and pass because their imports (`yascheduler.shared` typing shims, `yascheduler.entrypoints` path constants) flow downward through the layer direction

### Requirement: Layers contract configuration

The `[tool.importlinter]` section in `pyproject.toml` SHALL be
configured with:

- `root_package = "yascheduler"`.
- `exclude_type_checking_imports = true` (imports inside `if TYPE_CHECKING:` guards are not flagged as R3 violations, since they are type-only references with no runtime dependency).
- A `layers` contract with the name `Clean architecture layers` and `layers = ["yascheduler.entrypoints", "yascheduler.infra", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`.
- Dev dependency pinned as `import-linter >=2.5,<2.6` (the upper bound is required because `import-linter 2.6+` dropped Python 3.9 support, and the project pins `python >=3.9`).

No `forbidden` contract entry exists; the `layers` contract is the sole import-linter contract.

#### Scenario: pyproject.toml contains required keys
- **WHEN** `pyproject.toml` is parsed
- **THEN** the `[tool.importlinter]` section contains `root_package`, `exclude_type_checking_imports`, and one `[[tool.importlinter.contracts]]` entry of type `layers` with `yascheduler.entrypoints` as the 1st layer and `yascheduler.shared` as the 5th layer; no `forbidden` contract entry exists

#### Scenario: TYPE_CHECKING imports not flagged
- **WHEN** a module in `yascheduler.application` contains an import under `if TYPE_CHECKING:` that references a symbol in `yascheduler.infra`
- **THEN** the `layers` contract does NOT report a violation (the import is type-only)

#### Scenario: Module-level imports still flagged
- **WHEN** a module in `yascheduler.application` contains a module-level import (not under `TYPE_CHECKING`) from `yascheduler.infra`
- **THEN** the `layers` contract reports a violation (unless covered by `ignore_imports`)

#### Scenario: import-linter version compatible with Python 3.9
- **WHEN** the dev environment installs with `python >=3.9`
- **THEN** `import-linter >=2.5,<2.6` is installed and `lint-imports` runs without Python-version errors, and the `layers` contract type is recognized

### Requirement: Domain package facade contents

`yascheduler/domain/__init__.py` SHALL re-export the following
categories of symbols as the public surface of the domain layer:

- **Events** (already exported today; no regression): `DomainEvent`, `Event`, `TaskAbandoned`, `TaskAllocated`, `TaskCompleted`, `TaskCreated`, `TaskFailed`.
- **Model**: `Task` and related domain entities defined in `yascheduler.domain.model`.
- **Engine types**: `Engine`, `EngineRepository`, `LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`, `Deploy` from `yascheduler.domain.engine` (re-exported via `yascheduler.domain.model`).
- **Exceptions**: the existing `DomainError` tree from `yascheduler.domain.exceptions`.
- **Ports**: `TaskRepository`, `NodeRepository`, `MachineRepository`, `MachineSession`, `MachineOperations`, `CloudProvisioner` Protocols from `yascheduler.domain.ports`.

#### Scenario: Domain facade exposes all required categories
- **WHEN** a consumer imports `from yascheduler.domain import Task, TaskCreated, DomainError, TaskRepository, NodeRepository, MachineRepository, MachineSession, MachineOperations, CloudProvisioner`
- **THEN** all symbols resolve without ImportError

#### Scenario: Domain facade exposes Engine types
- **WHEN** a consumer imports `from yascheduler.domain import Engine, EngineRepository, Deploy, LocalFilesDeploy, LocalArchiveDeploy, RemoteArchiveDeploy`
- **THEN** all six symbols resolve without ImportError

#### Scenario: Domain exception tree unchanged
- **WHEN** the existing `DomainError` tree in `yascheduler/domain/exceptions.py` is inspected
- **THEN** no exception classes exist beyond the existing hierarchy

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
  re-exported through `yascheduler.entrypoints.paths` — downstream
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
  `yascheduler.client` (the shim) nor re-exported from
  `yascheduler.shared`; it is a private helper in
  `yascheduler.entrypoints.client` (inlined from the former
  `yascheduler.shared.async_utils`). The deep import path
  `from yascheduler.shared import to_sync` is NOT preserved (no compat
  shim); this is a **BREAKING** change for downstream code that pinned
  the deep module path (no such caller is known — the six CLI consumers
  were removed by the archived `consolidate-daemon-entrypoints` change,
  leaving `yascheduler.entrypoints.client` as the sole consumer).

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
- **THEN** all three symbols resolve without ImportError (re-exported via `yascheduler.entrypoints.paths`)

#### Scenario: Path constants re-exported via the entrypoints layer facade
- **WHEN** `yascheduler/__init__.py` is inspected for the source of its `CONFIG_FILE`, `LOG_FILE`, `PID_FILE` re-exports
- **THEN** it imports them from `yascheduler.entrypoints` (the layer facade), which in turn re-exports them from `yascheduler.entrypoints.paths`; the deep path `yascheduler.shared.variables` no longer exists

#### Scenario: to_sync is a private helper in entrypoints.client
- **WHEN** `yascheduler/entrypoints/client.py` is inspected for `to_sync`
- **THEN** `to_sync` is defined there as a module-private helper (not re-exported via `__all__`); it is NOT defined in `yascheduler.client` (the shim) and NOT re-exported from `yascheduler.shared`

#### Scenario: Old shared.async_utils path is gone
- **WHEN** a downstream consumer attempts `from yascheduler.shared.async_utils import to_sync` or `from yascheduler.shared import to_sync`
- **THEN** `ImportError` is raised (the module `yascheduler.shared.async_utils` no longer exists; the symbol `to_sync` is not re-exported from `yascheduler.shared`)

#### Scenario: compat.py re-exports Self and Unpack only
- **WHEN** `yascheduler/shared/compat.py` is inspected
- **THEN** the file does not exist at `yascheduler/compat.py`; `Self` and `Unpack` are importable via `from yascheduler.shared import Self, Unpack`; `ParamSpec` is NOT re-exported from `yascheduler.shared` (the symbol was consumed only by the former `to_sync` signature and moved with it into `yascheduler.entrypoints.client`)

#### Scenario: asleep_until is a private helper in application.orchestrator
- **WHEN** `yascheduler/application/orchestrator.py` is inspected for `asleep_until`
- **THEN** `asleep_until` is defined there as a module-private helper (e.g., `_asleep_until`); it is NOT re-exported from `yascheduler.shared`

#### Scenario: Old shared.async_utils asleep_until path is gone
- **WHEN** a downstream consumer attempts `from yascheduler.shared.async_utils import asleep_until` or `from yascheduler.shared import asleep_until`
- **THEN** `ImportError` is raised (the module `yascheduler.shared.async_utils` no longer exists)

### Requirement: Yascheduler client query method public contract

The `Yascheduler` class SHALL preserve its public query API across the
introduction of the `TaskId` domain value object. The class is defined in
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
  SHALL NOT change; their public `task_id`/`jobs` parameters stay `int` /
  `list[int]`.
 - Each query method SHALL return Mappings (a `Sequence[Mapping]` for the
   list variants `queue_get_tasks` / `queue_get_tasks_async`, an
   `Optional[Mapping]` for the single-task variants `queue_get_task` /
   `queue_get_task_async`) with EXACTLY the keys
   `{task_id, label, status, metadata, node}`. The flat `ip` and `cloud` keys
   are REMOVED and replaced by a nested `node` key. This is a **BREAKING**
   change to the facade dict shape (was `{task_id, label, ip, status, metadata,
   cloud}`).
 - The `task_id` value in each returned Mapping SHALL be a bare `int` (NOT a
   `TaskId`). The private `_task_to_dict(t: Task, nodes_by_id: dict[NodeId,
   Node])` helper is the sole extraction site: it builds the dict with
   `"task_id": t.task_id.value` so the public dict preserves the `int` shape.
  The `Yascheduler` facade is the **sole** `int`/`TaskId` marshalling boundary,
  in both directions: on input (`queue_get_task(task_id: int)` /
  `queue_get_tasks(jobs: list[int])`) it wraps `TaskId(task_id)` /
  `[TaskId(i) for i in jobs]` before calling the use cases / repository; on
  output it extracts `.value` via `_task_to_dict`.
- `queue_submit_task(...) -> int` SHALL stay `int`; it wraps `submit_task`
  (which now returns `TaskId`) and returns `(await submit_task(...)).value`.
- `status` SHALL be a `domain.TaskStatus` enum member (preserves `.name`
  access and cross-class IntEnum equality; NOT a plain `int`). Unchanged.
- `label` SHALL be the raw `task.label` string. Unchanged.
- `metadata` SHALL be the raw `task.context` metadata dict. Unchanged.
- `node` SHALL be an object built from `nodes_by_id.get(task.allocated_node_id)`,
  or `null` when the task has no allocated node (`allocated_node_id` is
  `None`). When non-null, the object has exactly `{ip, port, username, cloud}`:
  - `ip`: the raw `node.ip` string (replaces the flat `ip` key, which was
    `allocated_ip or ""`).
  - `port`: the raw `node.port` int.
  - `username`: the raw `node.username` string.
  - `cloud`: the raw `node.cloud` string, or `null` for static nodes.
  The `nodes_by_id` dict is obtained from the `query_tasks` use case, which
  now returns `(list[Task], dict[NodeId, Node])` (see the `use-cases`
  capability). The facade unpacks the tuple and passes `nodes_by_id` to
  `_task_to_dict`.

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

#### Scenario: Query returns five-key dict shape with nested node
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a non-empty result
- **THEN** each Mapping has exactly the keys `{task_id, label, status, metadata, node}`; the flat `ip` and `cloud` keys are ABSENT (replaced by the nested `node` key)a, cloud}` and no others

#### Scenario: task_id in returned dict is a bare int
- **WHEN** a returned Mapping's `task_id` value is inspected
- **THEN** it is a bare `int` (NOT a `TaskId` instance); the facade extracted `.value` via `_task_to_dict` so the public `int`-typed contract is preserved

#### Scenario: Facade wraps int to TaskId on input
- **WHEN** `queue_get_task(42)` or `queue_get_tasks_async(jobs=[1, 2, 3])` is called
- **THEN** the facade internally wraps `TaskId(42)` / `[TaskId(1), TaskId(2), TaskId(3)]` before calling the use case / repository (the public `int` signature is unchanged)

#### Scenario: queue_submit_task returns int
- **WHEN** `queue_submit_task(...)` completes successfully
- **THEN** it returns a bare `int` (the `.value` of the `TaskId` returned by `submit_task`); the public `-> int` contract is preserved

#### Scenario: Status field is a domain.TaskStatus member
- **WHEN** a returned Mapping's `status` value is inspected
- **THEN** it is an instance of `yascheduler.domain.TaskStatus` (not a plain `int`), with `.name` and `.value` matching the underlying IntEnum values 0/1/2

#### Scenario: node is null when task unallocated
- **WHEN** a Task with `allocated_node_id=None` is returned by a query method
- **THEN** the Mapping's `node` value is `null` (the flat `ip` and `cloud` keys are ABSENT; all node data is under the nested `node` key or `null`)

#### Scenario: Contract holds via each import path
- **WHEN** `Yascheduler` is imported via `from yascheduler import Yascheduler`, `from yascheduler.entrypoints import Yascheduler`, or `from yascheduler.client import Yascheduler`
- **THEN** all query-method scenarios above hold identically (the import path does not affect the public contract)

