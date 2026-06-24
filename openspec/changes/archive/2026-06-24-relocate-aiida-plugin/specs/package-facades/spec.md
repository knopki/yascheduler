## MODIFIED Requirements

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
`from yascheduler.entrypoints import …`. As follow-up changes migrate `di.py`,
`daemon_*.py`, and `infra/cli/*` into `entrypoints/`, their public symbols will
be added to this facade only when a cross-layer consumer requires them.

#### Scenario: Entrypoints facade re-exports Yascheduler
- **WHEN** a consumer imports `from yascheduler.entrypoints import Yascheduler`
- **THEN** the symbol resolves without ImportError

#### Scenario: Entrypoints facade is the sole public surface
- **WHEN** a module in `yascheduler.application`, `yascheduler.domain`, `yascheduler.infra`, `yascheduler.shared`, or `yascheduler.config` imports a symbol from `yascheduler.entrypoints`
- **THEN** the import goes through `yascheduler.entrypoints.__init__`, not a deep submodule path like `yascheduler.entrypoints.client`

#### Scenario: AiiDA plugin is not re-exported by the entrypoints facade
- **WHEN** the `entrypoints/__init__.py` facade is inspected
- **THEN** it re-exports only `Yascheduler`; `YaScheduler` and `YaschedJobResource` from `aiida_plugin.py` are NOT re-exported (plugin discovery is via the entry-point registry, not the facade)

#### Scenario: Empty facade is valid for future residents
- **WHEN** the `entrypoints` layer has not yet received a follow-up migration (e.g., CLI, daemon launchers)
- **THEN** the `entrypoints/__init__.py` facade contains only the re-exports required by current residents (`Yascheduler`), and adding new symbols is a deliberate lazy act, not an automatic re-export

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.config` — shared infrastructure, may be imported by any layer above `yascheduler.shared` in the `layers` contract. SHALL NOT be imported by `yascheduler.shared` (enforced by the separate `forbidden` contract).
- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.di` — composition root; may import from any layer. (Scheduled for migration into `yascheduler.entrypoints` in a follow-up change; remains at the package root in the interim.)
- `yascheduler.client` — compat shim re-exporting `Yascheduler` from `yascheduler.entrypoints.client`; preserves the deep import path `from yascheduler.client import Yascheduler` for external downstream consumers. Not a composition root (the real client implementation now lives in `yascheduler.entrypoints.client`).
- `yascheduler.daemon_systemd`, `yascheduler.daemon_sysv` — daemon launcher entry points. (Scheduled for migration into `yascheduler.entrypoints` in follow-up changes; remain at the package root in the interim.)

`yascheduler.shared` SHALL NOT contain business logic, domain types, or I/O. This clause is defense-in-depth beyond the layer-direction enforcement in the `layers` contract: the `layers` contract blocks `shared → {entrypoints, adapters, application, domain}` and the `forbidden` contract blocks `shared → config`, but neither contract can detect a contributor adding business logic or I/O that imports only stdlib/third-party. The clause gives reviewers a spec-grounded basis to reject such accretion.

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list (`yascheduler.config`, `yascheduler.data`, `yascheduler.di`, `yascheduler.client`, `yascheduler.daemon_systemd`, `yascheduler.daemon_sysv`) are not checked for R3 violations

#### Scenario: Outside-set modules still use facades
- **WHEN** `yascheduler.di` imports `Task` from `yascheduler.domain`
- **THEN** it imports via `from yascheduler.domain import Task` (R2 applies)

#### Scenario: yascheduler.client shim imports via facade
- **WHEN** `yascheduler.client` (the compat shim) imports `Yascheduler`
- **THEN** it imports via `from yascheduler.entrypoints import Yascheduler` (R2 applies), not via a deep submodule path

#### Scenario: yascheduler.shared contains no business logic or I/O
- **WHEN** a module under `yascheduler/shared/` is inspected
- **THEN** it contains only typing shims, pure runtime helpers, or process-global constants — no domain entities, no use-case orchestration, no SSH/DB/HTTP/cloud I/O

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