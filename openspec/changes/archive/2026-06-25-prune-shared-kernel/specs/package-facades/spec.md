## MODIFIED Requirements

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.config` — shared infrastructure, may be imported by any layer above `yascheduler.shared` in the `layers` contract. SHALL NOT be imported by `yascheduler.shared` (enforced by the separate `forbidden` contract).
- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.client` — compat shim re-exporting `Yascheduler` from `yascheduler.entrypoints.client`; preserves the deep import path `from yascheduler.client import Yascheduler` for external downstream consumers. Not a composition root (the real client implementation now lives in `yascheduler.entrypoints.client`).

The composition root formerly at `yascheduler.di` (package root) now lives
at `yascheduler.entrypoints.di` and is therefore inside the
`yascheduler.entrypoints` layer; it is no longer in the outside-layer-set
and is subject to R3. Its imports (`yascheduler.infra`,
`yascheduler.application`, `yascheduler.domain`) flow in the layer
direction and pass the contract.

`yascheduler.shared` is the shared kernel: it SHALL contain only typing
shims (and similar cross-cutting primitives) consumed by ≥2 architectural
layers. A module whose consumers are all within a single architectural
layer belongs to that layer, not to `yascheduler.shared`. This positive
definition is the primary membership rule. As a second guardrail,
`yascheduler.shared` SHALL NOT contain business logic, domain types, or
SSH/DB/HTTP/cloud I/O — defense-in-depth beyond the layer-direction
enforcement in the `layers` contract (the `layers` contract blocks
`shared → {entrypoints, adapters, application, domain}` and the
`forbidden` contract blocks `shared → config`, but neither contract can
detect a contributor adding business logic or I/O that imports only
stdlib/third-party; the clause gives reviewers a spec-grounded basis to
reject such accretion).

#### Scenario: Outside-set modules not flagged for layer direction
- **WHEN** the `layers` contract runs
- **THEN** modules in the outside-set list (`yascheduler.config`, `yascheduler.data`, `yascheduler.client`) are not checked for R3 violations

#### Scenario: Composition root is layer-checked after migration
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

#### Scenario: Daemon launchers are layer-checked after migration
- **WHEN** the `layers` contract runs
- **THEN** `yascheduler.entrypoints.cli.daemon_systemd` and `yascheduler.entrypoints.cli.daemon_sysv` (under the `yascheduler.entrypoints` layer) ARE checked for R3 violations like any other entrypoints-layer module, and pass because their imports (`yascheduler.infra.cli.daemonize`, `yascheduler.shared` typing shims, `yascheduler.entrypoints` path constants) flow downward through the layer direction

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
`SSHMachineGateway`, `PostgresUnitOfWork`, `resolve_adapter`,
`webhook_handler` from `yascheduler.infra` — all via layer facades (R2).

#### Scenario: Entrypoints facade re-exports Yascheduler, composition root, and path constants
- **WHEN** a consumer imports `from yascheduler.entrypoints import Yascheduler, make_daemon, make_cli_deps, CLIDeps, CONFIG_FILE, LOG_FILE, PID_FILE`
- **THEN** all seven symbols resolve without ImportError

#### Scenario: Entrypoints facade is the sole public surface
- **WHEN** a module in `yascheduler.application`, `yascheduler.domain`, `yascheduler.infra`, `yascheduler.shared`, or `yascheduler.config` imports a symbol from `yascheduler.entrypoints`
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