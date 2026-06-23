## Purpose

Define the package-facade import discipline for `yascheduler`: clean-architecture layer direction (R3, enforced via `import-linter`), within-package relative imports (R1), cross-package facade imports via the layer's `__init__.py` (R2), the lazy-publication policy, outside-layer-set exemptions, residual-edge documentation, and the extended facade contents required for R2 retroactive compliance across the codebase.

## Requirements

### Requirement: Layer direction (R3)

The system SHALL enforce the import direction
`yascheduler.adapters → yascheduler.application → yascheduler.domain`
via an `import-linter` `layers` contract configured in `pyproject.toml`.
`yascheduler.adapters` may import from `yascheduler.application` and
`yascheduler.domain`. `yascheduler.application` may import from
`yascheduler.domain`. `yascheduler.domain` SHALL NOT import from any
other layer in the project. Both direct and indirect imports are checked.

#### Scenario: Adapter imports from domain — allowed
- **WHEN** a module in `yascheduler.adapters` imports a symbol from `yascheduler.domain`
- **THEN** the `layers` contract reports no violation

#### Scenario: Application imports from adapters at module level — violation
- **WHEN** a module in `yascheduler.application` imports a symbol from `yascheduler.adapters` at module level (not under `TYPE_CHECKING`)
- **THEN** the `layers` contract reports a violation

#### Scenario: Domain imports from application or adapters — violation
- **WHEN** any module in `yascheduler.domain` imports from `yascheduler.application` or `yascheduler.adapters`
- **THEN** the `layers` contract reports a violation

#### Scenario: Indirect imports are caught
- **WHEN** a module in `yascheduler.domain` imports a module that (transitively) imports from `yascheduler.application`
- **THEN** the `layers` contract reports a violation

### Requirement: Within-package relative imports (R1)

The system SHALL use single-level relative import syntax (`from .foo import Bar`)
for imports between sibling modules inside the same package directory.
Parent-traversal relative imports (`from .. import`, `from ... import`,
`from .... import`, etc.) SHALL NOT appear anywhere in the `yascheduler`
package tree — they obscure the dependency direction and cross package
boundaries silently. Imports that need to reach a parent or sibling
package SHALL use absolute facade paths (R2). Absolute self-references
(e.g., a module in `yascheduler.adapters.cli` importing another module
in the same package via `from yascheduler.adapters.cli.check_status import ...`)
SHALL NOT appear inside that package.

#### Scenario: adapters/cli/__init__.py uses relative imports
- **WHEN** `yascheduler/adapters/cli/__init__.py` imports its own submodules (`check_status`, `daemonize`, `init`, `manage_node`, `show_nodes`, `submit`)
- **THEN** it uses `from .check_status import check_status` style, not `from yascheduler.adapters.cli.check_status import check_status`

#### Scenario: Domain modules use relative imports
- **WHEN** `yascheduler/domain/model.py` imports from another module in `yascheduler/domain/`
- **THEN** it uses `from .exceptions import ...` style, not `from yascheduler.domain.exceptions import ...`

#### Scenario: No parent-traversal relative imports anywhere
- **WHEN** any `.py` file under `yascheduler/` is inspected
- **THEN** no `from .. import`, `from ... import`, `from .... import` (or deeper) relative imports appear — only `from .` (single-level sibling) relative imports are permitted

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

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.config` — shared infrastructure, may be imported by any layer.
- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.di`, `yascheduler.client` — composition root; may import from any layer.
- `yascheduler.compat` — internal utility; not part of the public API.
- `yascheduler.aiida_plugin` — separate stable entry point; not part of the package's main public API.

The `yascheduler.db` module is removed entirely; it no longer appears in the
outside-layer-set exemption list, and no module in the `yascheduler/` package
SHALL import from `yascheduler.db`.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list are not checked for R3 violations

#### Scenario: Outside-set modules still use facades
- **WHEN** `yascheduler.di` imports `Task` from `yascheduler.domain`
- **THEN** it imports via `from yascheduler.domain import Task` (R2 applies)

#### Scenario: No module imports yascheduler.db
- **WHEN** the `yascheduler/` package (excluding nothing) is inspected after the change
- **THEN** no module imports `DB`, `TaskModel`, `NodeModel`, or `TaskStatus` from `yascheduler.db`, and no module references the `yascheduler.db` package (the module is deleted)

### Requirement: Layers contract configuration

The `[tool.importlinter]` section in `pyproject.toml` SHALL be
configured with:

- `root_package = "yascheduler"`.
- `exclude_type_checking_imports = true` (imports inside `if TYPE_CHECKING:` guards are not flagged as R3 violations, since they are type-only references with no runtime dependency).
- A single contract of type `layers` with the name `Clean architecture layers` and `layers = ["yascheduler.adapters", "yascheduler.application", "yascheduler.domain"]`.
- Dev dependency pinned as `import-linter >=2.5,<2.6` (the upper bound is required because `import-linter 2.6+` dropped Python 3.9 support, and the project pins `python >=3.9`).

#### Scenario: pyproject.toml contains required keys
- **WHEN** `pyproject.toml` is parsed
- **THEN** the `[tool.importlinter]` section contains `root_package`, `exclude_type_checking_imports`, and one `[[tool.importlinter.contracts]]` entry of type `layers`

#### Scenario: TYPE_CHECKING imports not flagged
- **WHEN** a module in `yascheduler.application` contains an import under `if TYPE_CHECKING:` that references a symbol in `yascheduler.adapters`
- **THEN** the `layers` contract does NOT report a violation (the import is type-only)

#### Scenario: Module-level imports still flagged
- **WHEN** a module in `yascheduler.application` contains a module-level import (not under `TYPE_CHECKING`) from `yascheduler.adapters`
- **THEN** the `layers` contract reports a violation (unless covered by `ignore_imports`)

#### Scenario: import-linter version compatible with Python 3.9
- **WHEN** the dev environment installs with `python >=3.9`
- **THEN** `import-linter >=2.5,<2.6` is installed and `lint-imports` runs without Python-version errors

### Requirement: Documented residual edges

The layers contract SHALL include `ignore_imports` entries for two
specific module-level edges that violate R3, documented as residual
until the follow-up change `gateway-sftp-wrapping` removes them:

- `"yascheduler.application.consume_task -> yascheduler.adapters"`
- `"yascheduler.application.orchestrator -> yascheduler.adapters"`

These edges exist because the application code uses `backoff.on_exception(...)`
with the SSH exception tuples (`SFTPRetryExc`, `AllSSHRetryExc`), and the
gateway currently exposes a raw asyncssh `SFTPClient` via `get_sftp()` —
so gateway-side exception translation cannot reach the SFTP call sites.
Properly fixing the violations requires a gateway SFTP refactor tracked
in the follow-up change `gateway-sftp-wrapping`. These two edges are
**R2-resolved and R3-residual**: the symbols are now reached through the
`yascheduler.adapters` layer facade (R2-compliant), but the
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

### Requirement: Broad ignore_imports tradeoff

The two `ignore_imports` entries in the `layers` contract SHALL use the
**layer facade path** (`yascheduler.application.{consume_task,orchestrator} -> yascheduler.adapters`)
rather than a deep path. This is broader than a deep-path carve-out:
any future module-level `from yascheduler.adapters import <anything>`
added to `consume_task.py` or `orchestrator.py` would be silently
suppressed by the same edge — not just the SSH-exception tuples the
prose justifies. The tradeoff is deliberate (matches the layer-facade
import form); reviewers MUST scrutinize any new adapter import in
those two files until the follow-up change `gateway-sftp-wrapping`
removes the residuals entirely.

#### Scenario: Reviewer scrutinizes new adapter imports in residual files
- **WHEN** a contributor adds a new module-level `from yascheduler.adapters import X` to `consume_task.py` or `orchestrator.py`
- **THEN** the reviewer verifies the import is justified (same shape as the residual) or requires the contributor to fix forward

### Requirement: Public API stability

The system SHALL preserve the existing public API surface of the
`yascheduler` package across changes. Public API is defined as: exported
symbols, constructor and method signatures (parameter positions and names,
return shapes), and documented behavior. Backward-compatible extensions
(adding keyword-only optional parameters, refining internal
implementation, adding new public symbols) are permitted; breaking
changes (removing or repositioning parameters, changing return shapes,
removing exported symbols) SHALL be treated as a new capability requiring
explicit spec coverage.

- `yascheduler/__init__.py` exports (`Yascheduler`, `CONFIG_FILE`,
  `LOG_FILE`, `PID_FILE`, `__version__`) SHALL remain resolvable.
- `yascheduler.aiida_plugin` (AiiDA scheduler entrypoint) SHALL remain
  loadable with identical behavior.
- `yascheduler.client` SHALL preserve its public constructor and method
  signatures: zero-arg and positional callsites remain valid; keyword-only
  optional parameters may be added (e.g., for test injection); internal
  implementation may change without notice.
- `yascheduler.compat` SHALL remain internal (not public surface).

#### Scenario: Yascheduler symbol resolves with backward-compatible signature
- **WHEN** a downstream consumer imports `from yascheduler import Yascheduler`
- **THEN** the symbol resolves and the zero-arg constructor `Yascheduler()` and the positional constructors `Yascheduler(config_path)` / `Yascheduler(config_path, logger)` remain valid

#### Scenario: Backward-compatible constructor extension permitted
- **WHEN** a change adds a keyword-only optional parameter to `Yascheduler.__init__` (e.g., `deps_factory` for test injection)
- **THEN** existing callsites `Yascheduler()`, `Yascheduler(config_path)`, `Yascheduler(config_path, logger)` remain valid without modification

#### Scenario: AiiDA plugin still loads
- **WHEN** the AiiDA scheduler plugin entrypoint is loaded
- **THEN** it loads and behaves identically to before the change

#### Scenario: compat.py remains internal
- **WHEN** `yascheduler/compat.py` is inspected
- **THEN** it is not added to any facade's public re-exports

### Requirement: Yascheduler client query method public contract

The `Yascheduler` class in `yascheduler/client.py` SHALL preserve its
public query API across the UoW migration:

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
