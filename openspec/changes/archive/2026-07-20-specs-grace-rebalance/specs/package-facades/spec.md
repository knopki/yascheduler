## MODIFIED Requirements

### Requirement: Layer direction (R3)

The system SHALL enforce the import direction
`yascheduler.entrypoints → yascheduler.infra → yascheduler.application → yascheduler.domain → yascheduler.shared`
via an `import-linter` `layers` contract configured in `pyproject.toml`.
Both direct and indirect imports are checked. `yascheduler.shared` is the
bottom layer and SHALL NOT import from any other `yascheduler` layer.

The contract is enforced by `import-linter` at lint time. Per-symbol
violations are not enumerated as separate scenarios — the contract is the
guard.

#### Scenario: Adapter imports from domain — allowed
- **WHEN** a module in `yascheduler.infra` imports a symbol from `yascheduler.domain`
- **THEN** the `layers` contract reports no violation

#### Scenario: Domain imports from application or adapters — violation
- **WHEN** any module in `yascheduler.domain` imports from `yascheduler.application` or `yascheduler.infra`
- **THEN** the `layers` contract reports a violation

#### Scenario: yascheduler.shared imports only stdlib and third-party
- **WHEN** any module in `yascheduler.shared` is inspected for its imports
- **THEN** it imports only from the standard library, third-party packages, and sibling modules within `yascheduler.shared`

### Requirement: Within-package relative imports (R1)

Modules within the same package SHALL use relative imports
(`from .xxx import yyy`) for symbols from sibling modules in the same
package. Only single-level sibling relative imports (`from .`) are
permitted — parent-traversal (`from ..`, `from ...`, deeper) SHALL NOT
appear.

#### Scenario: Domain modules use relative imports
- **WHEN** a domain module imports from another module in the domain package
- **THEN** it uses `from .exceptions import ...` style, not `from yascheduler.domain.exceptions import ...`

#### Scenario: No parent-traversal relative imports anywhere
- **WHEN** any `.py` file under `yascheduler/` is inspected
- **THEN** no `from .. import`, `from ... import`, `from .... import` (or deeper) relative imports appear — only `from .` (single-level sibling) relative imports are permitted

### Requirement: Cross-package facade imports (R2)

The system SHALL import symbols from another package via that package's
`__init__.py` only. For the architectural layers, each layer's `__init__.py`
is the sole public surface for cross-layer consumers:

- `yascheduler.infra` — sole entry point for `application` and composition root.
- `yascheduler.application` — sole entry point for adapters and composition root.
- `yascheduler.domain` — sole entry point for adapters, application, and composition root.

#### Scenario: Adapter imports Task via domain facade
- **WHEN** a module in `yascheduler.infra` needs `Task`
- **THEN** it uses `from yascheduler.domain import Task`, not `from yascheduler.domain.model import Task`

#### Scenario: Composition root imports use layer facades
- **WHEN** a module in the composition root imports a symbol from any layer
- **THEN** the import goes through the layer's `__init__.py` (e.g. `from yascheduler.infra import webhook_handler`), not through a subpackage facade or deep submodule path

### Requirement: Package facade as public surface (lazy publication)

Each subpackage of `yascheduler` SHALL designate its `__init__.py` as the
only public surface. Symbols are added to the facade lazily — only when an
external consumer actually needs them. Empty facades are valid. Adding a
symbol to a facade is a deliberate act, not an automatic re-export of all
non-underscore names.

#### Scenario: Empty facade is valid
- **WHEN** a subpackage's `__init__.py` is empty of public re-exports because no external consumer needs any of its symbols
- **THEN** the empty facade is the valid public surface for that subpackage

#### Scenario: Symbol added when consumer needs it
- **WHEN** an adapter needs `submit_task` from `yascheduler.application`
- **THEN** the application layer facade is updated to re-export `submit_task` from its defining submodule, and the adapter imports it via `from yascheduler.application import submit_task`

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not checked
for layer direction by R3) but SHALL still be subject to R2 (must use
facades for cross-package imports):

- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.client` — compat shim re-exporting `Yascheduler`.

`yascheduler.shared` SHALL contain only typing shims consumed by ≥2
architectural layers.

The exhaustive module list lives in `pyproject.toml` (the `layers` contract
config); the spec keeps only the behavioral rule.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list are not checked for R3 violations

#### Scenario: yascheduler.shared contains only cross-layer typing shims
- **WHEN** a module under `yascheduler/shared/` is inspected
- **THEN** it contains only typing shims consumed by ≥2 architectural layers

### Requirement: Domain package facade contents

The domain layer facade SHALL re-export events, model, engine types,
exceptions, and ports as the public surface of the domain layer.

#### Scenario: Domain facade exposes all required categories
- **WHEN** a consumer imports `from yascheduler.domain import Task, TaskCreated, DomainError, TaskRepository, NodeRepository, MachineRepository, MachineSession, CloudProvisioner`
- **THEN** all symbols resolve without ImportError

### Requirement: Extended facade contents (lazy publication driven by consumers)

The system SHALL re-export symbols from the infra layer facade, application
layer facade, and subpackage facades that external consumers already import
from their deep submodules. The exhaustive re-export list lives in the
facade modules' `MODULE_CONTRACT` SCOPE — the spec keeps only the
behavioral rule.

#### Scenario: Infra layer facade exposes the cross-layer surface
- **WHEN** a consumer imports `from yascheduler.infra import SSHMachineRepository, TaskDeployer, OutputDownloader, OccupancyChecker, AllSSHRetryExc, SFTPRetryExc, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork`
- **THEN** all eleven symbols resolve without ImportError

#### Scenario: Application facade exposes UoW, Orchestrator, MessageBus, submit_task
- **WHEN** a consumer imports `from yascheduler.application import AbstractUnitOfWork, Orchestrator, MessageBus, submit_task`
- **THEN** all four symbols resolve without ImportError

### Requirement: Public API stability

The system SHALL preserve the existing public API surface of the
`yascheduler` package across changes. Public API is defined as: exported
symbols resolvable via `from yascheduler import <name>`, constructor and
method signatures (parameter positions and names, return shapes), and
documented behavior.

Backward-compatible extensions are permitted; breaking changes (removing or
repositioning parameters, changing return shapes, removing exported symbols)
SHALL be treated as a new capability requiring explicit spec coverage.

Key stability rules:

- The package facade exports SHALL remain resolvable.
- The deep import path `from yascheduler.client import Yascheduler` SHALL
  remain resolvable via the compat shim.
- The AiiDA scheduler entrypoint SHALL remain registered under the
  entry-point name `yascheduler` in `[project.entry-points."aiida.schedulers"]`.

The exhaustive current-export list lives in the package `MODULE_CONTRACT`
SCOPE — the spec keeps only the behavioral stability rule.

#### Scenario: Yascheduler symbol resolves with backward-compatible signature
- **WHEN** a downstream consumer imports `from yascheduler import Yascheduler`
- **THEN** the symbol resolves and the zero-arg and positional constructors remain valid

#### Scenario: Deep import path resolves via compat shim
- **WHEN** a downstream consumer imports `from yascheduler.client import Yascheduler`
- **THEN** the symbol resolves without ImportError

#### Scenario: AiiDA plugin still loads under its entry-point name
- **WHEN** the AiiDA scheduler plugin is discovered via `importlib.metadata.entry_points(group="aiida.schedulers")`
- **THEN** the entry-point named `yascheduler` resolves to the object path `yascheduler.entrypoints.aiida_plugin:YaScheduler`

### Requirement: Yascheduler facade public contract

The `Yascheduler` facade SHALL expose the query methods (`queue_get_tasks`,
`queue_get_tasks_async`, `queue_get_task`, `queue_get_task_async`) and the
submission method (`queue_submit_task`) with the public contract below.

Each query method SHALL return Mappings with EXACTLY the keys
`{task_id, label, status, metadata, node}` — a BREAKING change from the
former flat `ip` / `cloud` keys, replaced by a nested `node` key.

- The query-method signatures SHALL NOT change; the public `task_id`/`jobs`
  parameters stay `int` / `list[int]`.
- Each query method SHALL return Mappings (a `Sequence[Mapping]` for the
  list variants, an `Optional[Mapping]` for the single-task variants) with
  EXACTLY the keys `{task_id, label, status, metadata, node}`.
- The `task_id` value in each returned Mapping SHALL be a bare `int` (NOT a
  `TaskId`).
- `queue_submit_task(...) -> int` SHALL stay `int`.
- `status` SHALL be a `domain.TaskStatus` enum member (preserves `.name`
  access and cross-class IntEnum equality; NOT a plain `int`).
- `label` SHALL be the raw `task.label` string.
- `metadata` SHALL be a flat dict reconstructed from the typed `Task` fields
  plus `extra`: the six typed fields (`engine`, `remote_folder`,
  `local_folder`, `webhook_url`, `webhook_custom_params`, `error`) with
  `None` values omitted, then `**task.extra` merged.
- `node` SHALL be an object built from `nodes_by_id.get(task.allocated_node_id)`,
  or `null` when the task has no allocated node. When non-null, the object
  has exactly `{hostname, port, username, cloud}`:
  - `hostname`: the raw `node.hostname` string.
  - `port`: the raw `node.port` int.
  - `username`: the raw `node.username` string.
  - `cloud`: the raw `node.cloud` string, or `null` for static nodes.

The public contract applies identically across the package facade
(`from yascheduler import Yascheduler`), the entrypoints layer facade
(`from yascheduler.entrypoints import Yascheduler`), and the compat shim
(`from yascheduler.client import Yascheduler`).

#### Scenario: metadata dict is reconstructed from typed fields plus extra
- **WHEN** the extraction helper is called on a Task with `engine="cp2k"`, `remote_folder="/r"`, `local_folder=None`, `webhook_url=None`, `webhook_custom_params={"parent": 42}`, `error=None`, `extra={"input.in": "ATOMS"}`
- **THEN** the returned Mapping's `metadata` value is `{"engine": "cp2k", "remote_folder": "/r", "webhook_custom_params": {"parent": 42}, "input.in": "ATOMS"}` (None-valued `local_folder`/`webhook_url`/`error` omitted; `extra` merged in)

#### Scenario: metadata dict omits all None typed fields
- **WHEN** the extraction helper is called on a Task with `remote_folder=None`, `local_folder=None`, `webhook_url=None`, `error=None`, `extra={}`
- **THEN** the returned Mapping's `metadata` value contains only the non-None typed fields (e.g. `{"engine": "cp2k", "webhook_custom_params": {}}`)

#### Scenario: Zero-arg construction remains valid
- **WHEN** `Yascheduler()` is called with no arguments
- **THEN** the client is constructed successfully and `queue_get_tasks_async` is invokable

#### Scenario: deps_factory is keyword-only
- **WHEN** `Yascheduler(config_path, logger, make_cli_deps)` is called with `deps_factory` as a positional argument
- **THEN** `TypeError` is raised (the parameter is keyword-only via `*,`)

#### Scenario: task_id in returned Mapping is bare int
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a non-empty result
- **THEN** each Mapping has exactly the keys `{task_id, label, status, metadata, node}`; the flat `ip` and `cloud` keys are ABSENT (replaced by the nested `node` key)

#### Scenario: task_id value is bare int not TaskId
- **WHEN** the `task_id` value in a returned Mapping is inspected
- **THEN** it is a bare `int` (NOT a `TaskId` instance)

#### Scenario: queue_get_task single-task returns Optional Mapping
- **WHEN** `queue_get_task(42)` is called and the task exists
- **THEN** it returns a Mapping with exactly `{task_id, label, status, metadata, node}` (NOT a list); `queue_get_task(99999)` for a missing task returns `None`

#### Scenario: node object shape when allocated
- **WHEN** the extraction helper is called on a Task with `allocated_node_id=NodeId(7)` and `nodes_by_id={NodeId(7): Node(node_id=NodeId(7), hostname="10.0.0.1", port=22, username="u", cloud="hetzner", ...)}`
- **THEN** the `node` value is `{"hostname": "10.0.0.1", "port": 22, "username": "u", "cloud": "hetzner"}`

#### Scenario: node is null when not allocated
- **WHEN** the extraction helper is called on a Task with `allocated_node_id=None`
- **THEN** the `node` value is `None` (null)

#### Scenario: queue_submit_task returns bare int
- **WHEN** `queue_submit_task(...)` is called
- **THEN** it returns a bare `int` (NOT a `TaskId`)

## REMOVED Requirements

### Requirement: Layers contract configuration

REMOVED — the requirement restated the `[tool.importlinter]` keys
(`root_package`, `exclude_type_checking_imports`, one
`[[tool.importlinter.contracts]]` entry of type `layers`). This is
configuration-file content, not behavior. The `import-linter` contract is
the guard for R3; `pyproject.toml` is the source of truth for its own keys.
The "Adapter imports from domain — allowed" / "Domain imports from
application or adapters — violation" scenarios are retained under the
modified `Layer direction (R3)` requirement above.

### Requirement: Compat shim for yascheduler.client

REMOVED as a standalone requirement — the deep-import-path behavior is
already covered by the modified `Public API stability` scenario "Deep import
path resolves via compat shim". The shim module's contents (which symbols it
re-exports, which it does NOT) live in the shim's `MODULE_CONTRACT` SCOPE.
The "Shim does not re-export Config" scenario is dropped because the
negative enumeration is shape, not behavior.

### Requirement: Entrypoints layer facade

REMOVED as a standalone requirement — the eight-symbol enumeration
(`Yascheduler`, `make_daemon`, `make_cli_deps`, `CLIDeps`, `Config`,
`CONFIG_FILE`, `LOG_FILE`, `PID_FILE`) is shape and lives in the
entrypoints `MODULE_CONTRACT` SCOPE. The behavioral rule ("entrypoints
facade is the layer facade for the entrypoints layer") is already covered
by the modified `Cross-package facade imports (R2)` requirement.

### Requirement: Per-symbol R1/R2/R3 scenarios

REMOVED — the per-symbol scenarios that re-pinned the same R1/R2/R3 rules
("Application imports from adapters at module level — violation", "Indirect
imports are caught", "yascheduler.shared imports from adapters — violation",
"Entrypoints imports from infra — allowed", "Infra imports from entrypoints
— violation", "Application imports from entrypoints — violation",
"Composition root imports from infra — allowed", "entrypoints CLI module
uses relative imports", "Application imports adapter symbols via infra
layer facade", "Within-layer cross-subpackage imports also use the layer
facade", "Old deep paths are gone") are collapsed into the modified
R1/R2/R3 requirements' representative scenarios. The `import-linter`
contract is the guard; per-symbol scenarios are documentation noise.
