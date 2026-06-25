## MODIFIED Requirements

### Requirement: Layer direction (R3)

The system SHALL enforce the import direction
`yascheduler.entrypoints → yascheduler.infra → yascheduler.application → yascheduler.domain → yascheduler.shared`
via an `import-linter` `layers` contract configured in `pyproject.toml`.

`yascheduler.entrypoints` (the outermost layer, hosting driving adapters and
the composition root at `yascheduler.entrypoints.di`) may import from
`yascheduler.infra`, `yascheduler.application`, `yascheduler.domain`,
`yascheduler.shared`, and the outside-layer-set modules
(`yascheduler.config`, `yascheduler.data`, etc.). The composition root
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

#### Scenario: Composition root imports from infra — allowed
- **WHEN** `yascheduler.entrypoints.di` imports `PostgresUnitOfWork`, `SSHMachineGateway`, `CloudProvisionerImpl`, `resolve_adapter`, and `webhook_handler` from `yascheduler.infra`
- **THEN** the `layers` contract reports no violation (composition root is a resident of `yascheduler.entrypoints` and its imports flow in the layer direction)

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

`yascheduler.shared` SHALL NOT contain business logic, domain types, or I/O. This clause is defense-in-depth beyond the layer-direction enforcement in the `layers` contract: the `layers` contract blocks `shared → {entrypoints, adapters, application, domain}` and the `forbidden` contract blocks `shared → config`, but neither contract can detect a contributor adding business logic or I/O that imports only stdlib/third-party. The clause gives reviewers a spec-grounded basis to reject such accretion.

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

#### Scenario: yascheduler.shared contains no business logic or I/O
- **WHEN** a module under `yascheduler/shared/` is inspected
- **THEN** it contains only typing shims, pure runtime helpers, or process-global constants — no domain entities, no use-case orchestration, no SSH/DB/HTTP/cloud I/O

#### Scenario: Daemon launchers are layer-checked after migration
- **WHEN** the `layers` contract runs
- **THEN** `yascheduler.entrypoints.cli.daemon_systemd` and `yascheduler.entrypoints.cli.daemon_sysv` (under the `yascheduler.entrypoints` layer) ARE checked for R3 violations like any other entrypoints-layer module, and pass because their imports (`yascheduler.infra.cli.daemonize`, `yascheduler.shared` constants) flow downward through the layer direction

### Requirement: Documented private-symbol carve-outs

The system SHALL maintain an explicit, spec-documented list of deep-path
imports that are exempt from R2 (facade) enforcement because the symbols
are deliberately private (leading underscore) and MUST NOT be promoted to
any facade. As of this change, the list is empty: the prior carve-out for
`yascheduler/di.py: from .adapters.cloud.adapters import _resolve_adapter`
is removed because the symbol was renamed to public `resolve_adapter` (in
the `review-hardening` change) and is now imported by the composition root
via the `infra` layer facade (`from yascheduler.infra import
resolve_adapter`), which is R2-compliant.

#### Scenario: No private-symbol carve-outs remain
- **WHEN** the R2 carve-out list is inspected
- **THEN** it is empty; every cross-package import in the codebase goes through a layer facade

#### Scenario: Private symbols stay on deep paths
- **WHEN** a leading-underscore symbol is needed by the composition root
- **THEN** it is NOT imported via a deep path that bypasses the layer facade; either it is promoted to public and re-exported by the facade, or it is not used across package boundaries at all

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

#### Scenario: Entrypoints facade re-exports Yascheduler and composition root
- **WHEN** a consumer imports `from yascheduler.entrypoints import Yascheduler, make_daemon, make_cli_deps, CLIDeps`
- **THEN** all four symbols resolve without ImportError

#### Scenario: Entrypoints facade is the sole public surface
- **WHEN** a module in `yascheduler.application`, `yascheduler.domain`, `yascheduler.infra`, `yascheduler.shared`, or `yascheduler.config` imports a symbol from `yascheduler.entrypoints`
- **THEN** the import goes through `yascheduler.entrypoints.__init__`, not a deep submodule path like `yascheduler.entrypoints.client`

#### Scenario: AiiDA plugin is not re-exported by the entrypoints facade
- **WHEN** the `entrypoints/__init__.py` facade is inspected
- **THEN** it re-exports `Yascheduler`, `make_daemon`, `make_cli_deps`, `CLIDeps`; `YaScheduler` and `YaschedJobResource` from `aiida_plugin.py` are NOT re-exported (plugin discovery is via the entry-point registry, not the facade)

#### Scenario: Daemon launchers are not re-exported by the entrypoints facade
- **WHEN** the `entrypoints/__init__.py` facade is inspected
- **THEN** `start_daemon` (from `entrypoints/cli/daemon_sysv.py`), `daemonize` (from `entrypoints/cli/daemonize.py`), and the `__main__` blocks of both `entrypoints/cli/daemon_systemd.py` and `entrypoints/cli/daemon_sysv.py` are NOT re-exported (the launchers are invoked by path from service templates or by the `yascheduler` console_script, not imported across layers)

#### Scenario: No deferred entrypoints migration remains
- **WHEN** the `entrypoints/__init__.py` change summary is inspected
- **THEN** it no longer mentions `infra/cli/` or `di.py` as a deferred follow-up; both migrations are complete

#### Scenario: CLI subpackage imports composition root via facade
- **WHEN** `yascheduler.entrypoints.cli.daemon_common` needs `make_daemon`
- **THEN** it imports `from yascheduler.entrypoints import make_daemon` (R2 via facade), not `from ..di import make_daemon` (deep sibling-cross-subpackage)

#### Scenario: Client sibling import of CLIDeps
- **WHEN** `yascheduler.entrypoints.client` needs `CLIDeps` and `make_cli_deps`
- **THEN** it imports `from .di import CLIDeps, make_cli_deps` (R1 sibling-relative, both residents of the flat `entrypoints` package)

#### Scenario: Composition root imports via layer facades
- **WHEN** `yascheduler.entrypoints.di` imports `Orchestrator` and `submit_task`
- **THEN** it imports `from yascheduler.application import Orchestrator, submit_task` (R2 via the `application` layer facade), not via a deep submodule path