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
the `entrypoints` layer, re-exporting the public wiring symbols (`Yascheduler`,
`make_daemon`, `make_cli_deps`, `CLIDeps`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`).
See `yascheduler/entrypoints/__init__.py` for the exact re-export list. The
facade is the sole public surface for cross-layer consumers; direct imports of
`yascheduler.entrypoints.client` from outside the layer SHALL NOT appear.

#### Scenario: Entrypoints facade re-exports the public wiring symbols
- **WHEN** a consumer imports `from yascheduler.entrypoints import Yascheduler, make_daemon, make_cli_deps, CLIDeps, CONFIG_FILE, LOG_FILE, PID_FILE`
- **THEN** all seven symbols resolve without ImportError

### Requirement: Compat shim for yascheduler.client

The file `yascheduler/client.py` SHALL be retained as a thin compatibility
shim that re-exports `Yascheduler` from `yascheduler.entrypoints.client`,
preserving the deep import path `from yascheduler.client import Yascheduler`.
The shim SHALL re-export exactly `Yascheduler` (`__all__ = ["Yascheduler"]`),
carry a GRACE-lite `MODULE_CONTRACT`, and SHALL NOT re-export `Config` or
contain any business logic.

#### Scenario: Deep import path resolves for external consumers
- **WHEN** a downstream consumer imports `from yascheduler.client import Yascheduler`
- **THEN** the symbol resolves without ImportError

#### Scenario: Shim does not re-export Config
- **WHEN** a test attempts `patch("yascheduler.client.Config.from_config_parser")`
- **THEN** the patch raises `AttributeError` (test must target `yascheduler.entrypoints.client.Config`)

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.client` — compat shim re-exporting `Yascheduler`.

`yascheduler.shared` SHALL contain only typing shims consumed by ≥2
architectural layers — no business logic, domain types, or I/O.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list are not checked for R3 violations

#### Scenario: yascheduler.shared contains only cross-layer typing shims
- **WHEN** a module under `yascheduler/shared/` is inspected
- **THEN** it contains only typing shims consumed by ≥2 architectural layers — no domain entities, no use-case orchestration, no I/O

### Requirement: Layers contract configuration

The `[tool.importlinter]` section in `pyproject.toml` SHALL be
configured with `root_package = "yascheduler"`,
`exclude_type_checking_imports = true`, a `layers` contract named
`Clean architecture layers` with layers
`["yascheduler.entrypoints", "yascheduler.infra", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`,
and dev dependency `import-linter >=2.5,<2.6`. No `forbidden` contract
entry exists.

#### Scenario: pyproject.toml contains required keys
- **WHEN** `pyproject.toml` is parsed
- **THEN** the `[tool.importlinter]` section contains `root_package`, `exclude_type_checking_imports`, and one `[[tool.importlinter.contracts]]` entry of type `layers`; no `forbidden` contract entry exists

### Requirement: Domain package facade contents

`yascheduler/domain/__init__.py` SHALL re-export events, model, engine types,
exceptions, and ports as the public surface of the domain layer. See
`yascheduler/domain/__init__.py` for the exact re-export list.

#### Scenario: Domain facade exposes all required categories
- **WHEN** a consumer imports `from yascheduler.domain import Task, TaskCreated, DomainError, TaskRepository, NodeRepository, MachineRepository, MachineSession, MachineOperations, CloudProvisioner`
- **THEN** all symbols resolve without ImportError

### Requirement: Extended facade contents (lazy publication driven by consumers)

The system SHALL re-export symbols from the infra layer facade
(`yascheduler/infra/__init__.py`), application layer facade
(`yascheduler/application/__init__.py`), and subpackage facades
(`yascheduler/infra/notifier/__init__.py`, `yascheduler/infra/cloud/__init__.py`,
`yascheduler/infra/persistence/__init__.py`) that external consumers already
import from their deep submodules. See the respective `__init__.py` files for
the exact re-export lists.

#### Scenario: Infra layer facade exposes the cross-layer surface
- **WHEN** a consumer imports `from yascheduler.infra import SSHMachineRepository, SSHMachineOperations, AllSSHRetryExc, SFTPRetryExc, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork`
- **THEN** all nine symbols resolve without ImportError

#### Scenario: Application facade exposes UoW, Orchestrator, MessageBus, submit_task
- **WHEN** a consumer imports `from yascheduler.application import AbstractUnitOfWork, Orchestrator, MessageBus, submit_task`
- **THEN** all four symbols resolve without ImportError

### Requirement: Public API stability

The system SHALL preserve the existing public API surface of the
`yascheduler` package across changes. Public API is defined as: exported
symbols resolvable via `from yascheduler import <name>`, constructor and
method signatures (parameter positions and names, return shapes), and
documented behavior. The public contract is keyed on the resolvable symbol,
NOT on the file path that defines it.

Backward-compatible extensions (adding keyword-only optional parameters,
refining internal implementation, adding new public symbols) are
permitted; breaking changes (removing or repositioning parameters,
changing return shapes, removing exported symbols) SHALL be treated as a
new capability requiring explicit spec coverage.

Key stability rules:
- `yascheduler/__init__.py` exports (`Yascheduler`, `CONFIG_FILE`,
  `LOG_FILE`, `PID_FILE`, `__version__`) SHALL remain resolvable.
- The deep import path `from yascheduler.client import Yascheduler` SHALL
  remain resolvable via the compat shim.
- The AiiDA scheduler entrypoint SHALL remain registered under the
  entry-point name `yascheduler` in `[project.entry-points."aiida.schedulers"]`.
- The deep import paths `from yascheduler.aiida_plugin import …`,
  `from yascheduler.shared import to_sync`, and
  `from yascheduler.shared.async_utils import …` are NOT preserved
  (no compat shim; breaking changes with no known downstream callers).

#### Scenario: Yascheduler symbol resolves with backward-compatible signature
- **WHEN** a downstream consumer imports `from yascheduler import Yascheduler`
- **THEN** the symbol resolves and the zero-arg and positional constructors remain valid

#### Scenario: Deep import path resolves via compat shim
- **WHEN** a downstream consumer imports `from yascheduler.client import Yascheduler`
- **THEN** the symbol resolves without ImportError

#### Scenario: AiiDA plugin still loads under its entry-point name
- **WHEN** the AiiDA scheduler plugin is discovered via `importlib.metadata.entry_points(group="aiida.schedulers")`
- **THEN** the entry-point named `yascheduler` resolves to the object path `yascheduler.entrypoints.aiida_plugin:YaScheduler`

#### Scenario: Old deep paths are gone
- **WHEN** a downstream consumer attempts `from yascheduler.aiida_plugin import YaScheduler` or `from yascheduler.shared import to_sync`
- **THEN** `ModuleNotFoundError` / `ImportError` is raised (no compat shim)

### Requirement: Yascheduler facade public contract

The `Yascheduler` facade SHALL expose the query methods (`queue_get_tasks`,
`queue_get_tasks_async`, `queue_get_task`, `queue_get_task_async`) and the
submission method (`queue_submit_task`) with the public contract below. This
delta modifies only the `metadata` field reconstruction source; all other
clauses (signatures, `task_id` int marshalling, `node` object shape, `status`
enum, `label` string, `queue_submit_task` return) are unchanged. Each query
method SHALL return Mappings with EXACTLY the keys
`{task_id, label, status, metadata, node}`. The `_task_to_dict` helper SHALL be
the sole extraction site and SHALL construct the `metadata` Mapping inline from
the typed `Task` fields plus `extra` (was `t.context.to_metadata()`).

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
- `metadata` SHALL be a flat dict reconstructed from the typed `Task` fields
  plus `extra` — the SAME shape that `TaskContext.to_metadata()` produced
  before the drop-task-context-entity change. `_task_to_dict` SHALL construct
  the dict inline: the six typed fields (`engine`, `remote_folder`,
  `local_folder`, `webhook_url`, `webhook_custom_params`, `error`) with `None`
  values omitted, then `**task.extra` merged. The public dict shape
  `{task_id, label, status, metadata, node}` is UNCHANGED — only the
  construction source changes (was `t.context.to_metadata()`, now inline
  reconstruction from `t.engine` / `t.remote_folder` / `t.local_folder` /
  `t.webhook_url` / `t.webhook_custom_params` / `t.error` / `t.extra`). This
  preserves wire compatibility for any caller parsing the `metadata` dict.
- `node` SHALL be an object built from `nodes_by_id.get(task.allocated_node_id)`,
  or `null` when the task has no allocated node (`allocated_node_id` is
  `None`). When non-null, the object has exactly `{ip, port, username, cloud}`:
  - `ip`: the raw `node.ip` string (replaces the flat `ip` key, which was
    `allocated_ip or ""`).
  - `port`: the raw `node.port` int.
  - `username`: the raw `node.username` string.
  - `cloud`: the raw `node.cloud` string, or `null` for static nodes.
  The `nodes_by_id` dict is obtained from the `query_tasks` use case, which
  returns `(list[Task], dict[NodeId, Node])` (see the `use-cases`
  capability). The facade unpacks the tuple and passes `nodes_by_id` to
  `_task_to_dict`.

The public contract is keyed on the resolvable symbol and applies
identically whether `Yascheduler` is imported via the package facade
(`from yascheduler import Yascheduler`), the entrypoints layer facade
(`from yascheduler.entrypoints import Yascheduler`), or the compat shim
(`from yascheduler.client import Yascheduler`).

#### Scenario: metadata dict is reconstructed from typed fields plus extra
- **WHEN** `_task_to_dict(t, nodes_by_id)` is called on a Task with `engine="cp2k"`, `remote_folder="/r"`, `local_folder=None`, `webhook_url=None`, `webhook_custom_params={"parent": 42}`, `error=None`, `extra={"input.in": "ATOMS"}`
- **THEN** the returned Mapping's `metadata` value is `{"engine": "cp2k", "remote_folder": "/r", "webhook_custom_params": {"parent": 42}, "input.in": "ATOMS"}` (None-valued `local_folder`/`webhook_url`/`error` omitted; `extra` merged in) — the SAME shape that `TaskContext.to_metadata()` produced before the change

#### Scenario: metadata dict omits all None typed fields
- **WHEN** `_task_to_dict(t, nodes_by_id)` is called on a Task with `remote_folder=None`, `local_folder=None`, `webhook_url=None`, `error=None`, `extra={}`
- **THEN** the returned Mapping's `metadata` value contains only the non-None typed fields (e.g. `{"engine": "cp2k", "webhook_custom_params": {}}`); the None-valued fields are absent (preserving the `to_metadata()` omission behavior)

#### Scenario: metadata dict shape unchanged from caller perspective
- **WHEN** a caller inspects `queue_get_tasks_async(jobs=[1])` output before and after the drop-task-context-entity change
- **THEN** the `metadata` Mapping has the same keys and values for the same task (the reconstruction produces the same flat dict that `to_metadata()` did) — wire compatibility preserved

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
- **THEN** it is a bare `int` (NOT a `TaskId` instance); the facade extracted `.value` via `_task_to_dict` so the public `int`-typed contract is preserved

#### Scenario: queue_get_task single-task returns Optional Mapping
- **WHEN** `queue_get_task(42)` is called and the task exists
- **THEN** it returns a Mapping with exactly `{task_id, label, status, metadata, node}` (NOT a list); `queue_get_task(99999)` for a missing task returns `None`

#### Scenario: node object shape when allocated
- **WHEN** `_task_to_dict` is called on a Task with `allocated_node_id=NodeId(7)` and `nodes_by_id={NodeId(7): Node(ip="[IP]", port=22, username="u", cloud="hetzner", ...)}`
- **THEN** the `node` value is `{"ip": "[IP]", "port": 22, "username": "u", "cloud": "hetzner"}`

#### Scenario: node is null when not allocated
- **WHEN** `_task_to_dict` is called on a Task with `allocated_node_id=None`
- **THEN** the `node` value is `None` (null)

#### Scenario: queue_submit_task returns bare int
- **WHEN** `queue_submit_task(...)` is called
- **THEN** it returns a bare `int` (NOT a `TaskId`); the facade unwraps `.value` from the `submit_task` use case's `TaskId` return

#### Scenario: No TaskContext reference in _task_to_dict
- **WHEN** `_task_to_dict` is inspected for `TaskContext` or `to_metadata` references
- **THEN** none are present (the dict is constructed inline from `t.engine`, `t.remote_folder`, `t.local_folder`, `t.webhook_url`, `t.webhook_custom_params`, `t.error`, `t.extra`)

