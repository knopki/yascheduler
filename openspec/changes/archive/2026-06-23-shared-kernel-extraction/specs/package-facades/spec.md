## ADDED Requirements

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
`yascheduler.client`, `yascheduler.db`, `yascheduler.aiida_plugin`) are
NOT in `forbidden_modules`. The practical risk of `yascheduler.shared`
importing an entry point, the legacy DB layer, or the AiiDA plugin is
negligible; only `yascheduler.config` creates a real cycle risk because
it is a peer utility module that already depends on `yascheduler.shared`.

#### Scenario: yascheduler.shared imports from yascheduler.config — violation
- **WHEN** a module in `yascheduler.shared` imports a symbol from `yascheduler.config`
- **THEN** the `forbidden` contract reports a violation

#### Scenario: yascheduler.config imports from yascheduler.shared — allowed
- **WHEN** a module in `yascheduler.config` imports `Self` from `yascheduler.shared`
- **THEN** no contract reports a violation (the `layers` contract does not cover `config` since it is outside-layer-set; the `forbidden` contract is directional and only blocks the reverse edge)

## MODIFIED Requirements

### Requirement: Layer direction (R3)

The system SHALL enforce the import direction
`yascheduler.adapters → yascheduler.application → yascheduler.domain → yascheduler.shared`
via an `import-linter` `layers` contract configured in `pyproject.toml`.
`yascheduler.adapters` may import from `yascheduler.application`,
`yascheduler.domain`, and `yascheduler.shared`. `yascheduler.application`
may import from `yascheduler.domain` and `yascheduler.shared`.
`yascheduler.domain` may import from `yascheduler.shared`.
`yascheduler.shared` SHALL NOT import from any other layer in the
project. Both direct and indirect imports are checked.

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

#### Scenario: yascheduler.shared imports from adapters — violation
- **WHEN** any module in `yascheduler.shared` imports from `yascheduler.adapters`, `yascheduler.application`, or `yascheduler.domain`
- **THEN** the `layers` contract reports a violation

#### Scenario: yascheduler.shared imports only stdlib and third-party
- **WHEN** any module in `yascheduler.shared` is inspected for its imports
- **THEN** it imports only from the standard library, third-party packages, and sibling modules within `yascheduler.shared` — never from any other `yascheduler` layer

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.config` — shared infrastructure, may be imported by any layer above `yascheduler.shared` in the `layers` contract. SHALL NOT be imported by `yascheduler.shared` (enforced by the separate `forbidden` contract).
- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.di`, `yascheduler.client` — composition root; may import from any layer.
- `yascheduler.db` — legacy, scheduled for deletion; MUST NOT be modified by this change.
- `yascheduler.aiida_plugin` — separate stable entry point; not part of the package's main public API.

`yascheduler.compat` (previously listed as an individual outside-layer-set module) is relocated under `yascheduler.shared` as `yascheduler.shared.compat`; the outside-layer-set exemption no longer applies to it — `yascheduler.shared` is now a 4th layer in the `layers` contract. `yascheduler.variables` (which was re-exported via `yascheduler/__init__.py` and consumed through that facade, never individually listed as outside-layer-set) is likewise relocated to `yascheduler.shared.variables` under the same layer.

`yascheduler.shared` SHALL NOT contain business logic, domain types, or I/O. This clause is defense-in-depth beyond the layer-direction enforcement in the `layers` contract: the `layers` contract blocks `shared → {adapters, application, domain}` and the `forbidden` contract blocks `shared → config`, but neither contract can detect a contributor adding business logic or I/O that imports only stdlib/third-party. The clause gives reviewers a spec-grounded basis to reject such accretion.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list are not checked for R3 violations

#### Scenario: Outside-set modules still use facades
- **WHEN** `yascheduler.di` imports `Task` from `yascheduler.domain`
- **THEN** it imports via `from yascheduler.domain import Task` (R2 applies)

#### Scenario: db.py is not modified
- **WHEN** the change is implemented
- **THEN** `yascheduler/db.py` is not touched (legacy, scheduled for deletion)

#### Scenario: yascheduler.shared contains no business logic or I/O
- **WHEN** a module under `yascheduler/shared/` is inspected
- **THEN** it contains only typing shims, pure runtime helpers, or process-global constants — no domain entities, no use-case orchestration, no SSH/DB/HTTP/cloud I/O

### Requirement: Layers contract configuration

The `[tool.importlinter]` section in `pyproject.toml` SHALL be
configured with:

- `root_package = "yascheduler"`.
- `exclude_type_checking_imports = true` (imports inside `if TYPE_CHECKING:` guards are not flagged as R3 violations, since they are type-only references with no runtime dependency).
- A `layers` contract with the name `Clean architecture layers` and `layers = ["yascheduler.adapters", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`.
- A `forbidden` contract with the name `Shared kernel has no config imports`, `source_modules = ["yascheduler.shared"]`, `forbidden_modules = ["yascheduler.config"]`.
- Dev dependency pinned as `import-linter >=2.5,<2.6` (the upper bound is required because `import-linter 2.6+` dropped Python 3.9 support, and the project pins `python >=3.9`). Both `layers` and `forbidden` contract types are supported in this version range.

#### Scenario: pyproject.toml contains required keys
- **WHEN** `pyproject.toml` is parsed
- **THEN** the `[tool.importlinter]` section contains `root_package`, `exclude_type_checking_imports`, one `[[tool.importlinter.contracts]]` entry of type `layers` with `yascheduler.shared` as the 4th layer, and one `[[tool.importlinter.contracts]]` entry of type `forbidden` with `source_modules = ["yascheduler.shared"]` and `forbidden_modules = ["yascheduler.config"]`

#### Scenario: TYPE_CHECKING imports not flagged
- **WHEN** a module in `yascheduler.application` contains an import under `if TYPE_CHECKING:` that references a symbol in `yascheduler.adapters`
- **THEN** the `layers` contract does NOT report a violation (the import is type-only)

#### Scenario: Module-level imports still flagged
- **WHEN** a module in `yascheduler.application` contains a module-level import (not under `TYPE_CHECKING`) from `yascheduler.adapters`
- **THEN** the `layers` contract reports a violation (unless covered by `ignore_imports`)

#### Scenario: import-linter version compatible with Python 3.9
- **WHEN** the dev environment installs with `python >=3.9`
- **THEN** `import-linter >=2.5,<2.6` is installed and `lint-imports` runs without Python-version errors, and both `layers` and `forbidden` contract types are recognized

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
  `LOG_FILE`, `PID_FILE`, `__version__`) SHALL remain resolvable. The
  path constants (`CONFIG_FILE`, `LOG_FILE`, `PID_FILE`) SHALL be
  re-exported through `yascheduler.shared.variables` — downstream
  consumers continue to import them via `from yascheduler import
  CONFIG_FILE` with no change.
- `yascheduler.aiida_plugin` (AiiDA scheduler entrypoint) SHALL remain
  loadable with identical behavior.
- `yascheduler.client` SHALL preserve its public constructor and method
  signatures: zero-arg and positional callsites remain valid; keyword-only
  optional parameters may be added (e.g., for test injection); internal
  implementation may change without notice. The `to_sync` function SHALL
  no longer be defined in `yascheduler.client`; it is relocated to
  `yascheduler.shared.async_utils` and re-exported via the
  `yascheduler.shared` facade.
- `yascheduler.compat` SHALL remain internal (not public surface). The
  module is relocated to `yascheduler.shared.compat`; the old path
  `yascheduler/compat.py` ceases to exist. This is not a public API break
  because `yascheduler.compat` was already declared internal.

#### Scenario: Yascheduler symbol resolves with backward-compatible signature
- **WHEN** a downstream consumer imports `from yascheduler import Yascheduler`
- **THEN** the symbol resolves and the zero-arg constructor `Yascheduler()` and the positional constructors `Yascheduler(config_path)` / `Yascheduler(config_path, logger)` remain valid

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
- **THEN** it imports `from yascheduler.shared import to_sync`; the symbol is no longer defined in `yascheduler.client`

#### Scenario: compat.py old path removed
- **WHEN** `yascheduler/compat.py` is inspected
- **THEN** the file does not exist; `Self` and `ParamSpec` are importable only via `from yascheduler.shared import Self, ParamSpec`