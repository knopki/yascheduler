## MODIFIED Requirements

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
(`entrypoints/cli/daemon_systemd.py` and
`entrypoints/cli/daemon_sysv.py`) are NOT re-exported by the facade either:
they are invoked by path from the systemd unit file and SysV init.d script
templates (via `%YASCHEDULER_DAEMON_FILE%` substitution produced by `yainit`),
not imported across layers. The `daemonize` entry point
(`entrypoints/cli/daemonize.py`) is likewise NOT re-exported by the facade: it
is invoked by the `yascheduler` console_script, not imported across layers.
With `infra/cli/` liquidated, no deferred `infra/cli/*` migration remains.

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
- **THEN** it re-exports only `Yascheduler`; `start_daemon` (from `entrypoints/cli/daemon_sysv.py`), `daemonize` (from `entrypoints/cli/daemonize.py`), and the `__main__` blocks of both `entrypoints/cli/daemon_systemd.py` and `entrypoints/cli/daemon_sysv.py` are NOT re-exported (the launchers are invoked by path from service templates or by the `yascheduler` console_script, not imported across layers)

#### Scenario: No deferred infra/cli migration remains
- **WHEN** the `entrypoints/__init__.py` change summary is inspected
- **THEN** it no longer mentions `infra/cli/` as a deferred follow-up; the migration is complete