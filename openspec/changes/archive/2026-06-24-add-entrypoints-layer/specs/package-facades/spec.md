## ADDED Requirements

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
consumer actually needs them. As follow-up changes migrate `di.py`,
`aiida_plugin.py`, `daemon_*.py`, and `infra/cli/*` into `entrypoints/`, their
public symbols will be added to this facade.

#### Scenario: Entrypoints facade re-exports Yascheduler
- **WHEN** a consumer imports `from yascheduler.entrypoints import Yascheduler`
- **THEN** the symbol resolves without ImportError

#### Scenario: Entrypoints facade is the sole public surface
- **WHEN** a module in `yascheduler.application`, `yascheduler.domain`, `yascheduler.infra`, `yascheduler.shared`, or `yascheduler.config` imports a symbol from `yascheduler.entrypoints`
- **THEN** the import goes through `yascheduler.entrypoints.__init__`, not a deep submodule path like `yascheduler.entrypoints.client`

#### Scenario: Empty facade is valid for future residents
- **WHEN** the `entrypoints` layer has not yet received a follow-up migration (e.g., CLI, daemon launchers)
- **THEN** the `entrypoints/__init__.py` facade contains only the re-exports required by current residents (`Yascheduler`), and adding new symbols is a deliberate lazy act, not an automatic re-export

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

## MODIFIED Requirements

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

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.config` — shared infrastructure, may be imported by any layer above `yascheduler.shared` in the `layers` contract. SHALL NOT be imported by `yascheduler.shared` (enforced by the separate `forbidden` contract).
- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.di` — composition root; may import from any layer. (Scheduled for migration into `yascheduler.entrypoints` in a follow-up change; remains at the package root in the interim.)
- `yascheduler.client` — compat shim re-exporting `Yascheduler` from `yascheduler.entrypoints.client`; preserves the deep import path `from yascheduler.client import Yascheduler` for external downstream consumers. Not a composition root (the real client implementation now lives in `yascheduler.entrypoints.client`).
- `yascheduler.aiida_plugin` — separate stable entry point; not part of the package's main public API. (Scheduled for migration into `yascheduler.entrypoints` in a follow-up change; remains at the package root in the interim.)
- `yascheduler.daemon_systemd`, `yascheduler.daemon_sysv` — daemon launcher entry points. (Scheduled for migration into `yascheduler.entrypoints` in follow-up changes; remain at the package root in the interim.)

`yascheduler.shared` SHALL NOT contain business logic, domain types, or I/O. This clause is defense-in-depth beyond the layer-direction enforcement in the `layers` contract: the `layers` contract blocks `shared → {entrypoints, adapters, application, domain}` and the `forbidden` contract blocks `shared → config`, but neither contract can detect a contributor adding business logic or I/O that imports only stdlib/third-party. The clause gives reviewers a spec-grounded basis to reject such accretion.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list (`yascheduler.config`, `yascheduler.data`, `yascheduler.di`, `yascheduler.client`, `yascheduler.aiida_plugin`, `yascheduler.daemon_systemd`, `yascheduler.daemon_sysv`) are not checked for R3 violations

#### Scenario: Outside-set modules still use facades
- **WHEN** `yascheduler.di` imports `Task` from `yascheduler.domain`
- **THEN** it imports via `from yascheduler.domain import Task` (R2 applies)

#### Scenario: yascheduler.client shim imports via facade
- **WHEN** `yascheduler.client` (the compat shim) imports `Yascheduler`
- **THEN** it imports via `from yascheduler.entrypoints import Yascheduler` (R2 applies), not via a deep submodule path

#### Scenario: yascheduler.shared contains no business logic or I/O
- **WHEN** a module under `yascheduler/shared/` is inspected
- **THEN** it contains only typing shims, pure runtime helpers, or process-global constants — no domain entities, no use-case orchestration, no SSH/DB/HTTP/cloud I/O

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
- `yascheduler.aiida_plugin` (AiiDA scheduler entrypoint) SHALL remain
  loadable with identical behavior (the module is not moved by this
  change; a follow-up change will relocate it into `entrypoints/`).
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

#### Scenario: AiiDA plugin still loads
- **WHEN** the AiiDA scheduler plugin entrypoint is loaded
- **THEN** it loads and behaves identically to before the change

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