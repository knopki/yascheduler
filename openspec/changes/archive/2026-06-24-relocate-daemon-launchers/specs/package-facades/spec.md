## MODIFIED Requirements

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
(`entrypoints/daemon/daemon_systemd.py` and
`entrypoints/daemon/daemon_sysv.py`) are NOT re-exported by the facade either:
they are invoked by path from the systemd unit file and SysV init.d script
templates (via `%YASCHEDULER_DAEMON_FILE%` substitution produced by `yainit`),
not imported across layers. As follow-up changes migrate `di.py` and
`infra/cli/*` into `entrypoints/`, their public symbols will be added to this
facade only when a cross-layer consumer requires them.

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
- **THEN** it re-exports only `Yascheduler`; `start_daemon` (from `entrypoints/daemon/daemon_sysv.py`) and the `__main__` blocks of both `entrypoints/daemon/daemon_systemd.py` and `entrypoints/daemon/daemon_sysv.py` are NOT re-exported (the launchers are invoked by path from service templates, not imported across layers)

#### Scenario: Empty facade is valid for future residents
- **WHEN** the `entrypoints` layer has not yet received a follow-up migration (e.g., CLI)
- **THEN** the `entrypoints/__init__.py` facade contains only the re-exports required by current residents (`Yascheduler`), and adding new symbols is a deliberate lazy act, not an automatic re-export

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
- **THEN** `yascheduler.entrypoints.daemon.daemon_systemd` and `yascheduler.entrypoints.daemon.daemon_sysv` (now under the `yascheduler.entrypoints` layer) ARE checked for R3 violations like any other entrypoints-layer module, and pass because their imports (`yascheduler.infra.cli.daemonize`, `yascheduler.shared` constants) flow downward through the layer direction