## MODIFIED Requirements

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