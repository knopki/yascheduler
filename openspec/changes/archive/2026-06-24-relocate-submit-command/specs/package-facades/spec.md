## MODIFIED Requirements

### Requirement: Within-package relative imports (R1)

Modules within the same package (e.g. `yascheduler.infra.cli`) SHALL use
relative imports (`from .xxx import yyy`) for symbols from other modules in
the same package. Absolute cross-package imports
(`from yascheduler.infra.cli.xxx import yyy`) of a sibling within the same
package SHALL NOT appear inside that package. This applies to intra-package
imports in `yascheduler.infra.cli`, `yascheduler.infra.persistence`,
`yascheduler.entrypoints.daemon`, and all other subpackages.

#### Scenario: infra/cli/__init__.py uses relative imports
- **WHEN** `yascheduler/infra/cli/__init__.py` imports its own submodules (`check_status`, `daemonize`, `manage_node`)
- **THEN** it uses `from .check_status import check_status` style, not `from yascheduler.infra.cli.check_status import check_status`
- **AND** it does NOT import `init`, `show_nodes`, or `submit` (which have moved to `yascheduler/entrypoints/cli/`)

#### Scenario: entrypoints/cli/__init__.py uses relative imports
- **WHEN** `yascheduler/entrypoints/cli/__init__.py` imports its own submodules
- **THEN** it uses `from .init import init` style, not `from yascheduler.entrypoints.cli.init import init`; `show_nodes` and `submit` are NOT re-exported by the facade (they are invoked by console_script, not imported across layers — same pattern as `init`)

#### Scenario: Domain modules use relative imports
- **WHEN** `yascheduler/domain/model.py` imports from another module in `yascheduler/domain/`
- **THEN** it uses `from .exceptions import ...` style, not `from yascheduler.domain.exceptions import ...`

#### Scenario: No parent-traversal relative imports anywhere
- **WHEN** any `.py` file under `yascheduler/` is inspected
- **THEN** no `from .. import`, `from ... import`, `from .... import` (or deeper) relative imports appear — only `from .` (single-level sibling) relative imports are permitted