## MODIFIED Requirements

### Requirement: Outside-layer-set exemptions

The following modules SHALL be outside the `layers` contract (not
checked for layer direction by R3) but SHALL still be subject to R2
(must use facades for cross-package imports):

- `yascheduler.data` — shared infrastructure, may be imported by any layer.
- `yascheduler.client` — compat shim re-exporting `Yascheduler` from
`yascheduler.entrypoints.client`; preserves the deep import path
`from yascheduler.client import Yascheduler` for external downstream
consumers. Not a composition root (the real client implementation now
lives in `yascheduler.entrypoints.client`).

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
- **THEN** modules in the outside-set list (`yascheduler.data`, `yascheduler.client`) are not checked for R3 violations

#### Scenario: yascheduler.config no longer in outside-set
- **WHEN** the `layers` contract runs
- **THEN** `yascheduler.config` is not present in the outside-set list (the package is deleted; the exemption is removed)

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

## REMOVED Requirements

### Requirement: Shared kernel config-import prohibition

The `forbidden` contract
("Shared kernel has no config imports",
`source_modules = ["yascheduler.shared"]`,
`forbidden_modules = ["yascheduler.config"]`) is removed. With
`yascheduler.config` deleted, the contract is vacuous — there is no
`yascheduler.config` module to forbid imports from.

#### Scenario: No forbidden contract for yascheduler.config
- **WHEN** the `[tool.importlinter]` section in `pyproject.toml` is parsed
- **THEN** no `forbidden` contract entry with `forbidden_modules = ["yascheduler.config"]` exists

## MODIFIED Requirements

### Requirement: Layers contract configuration

The `[tool.importlinter]` section in `pyproject.toml` SHALL be
configured with:

- `root_package = "yascheduler"`.
- `exclude_type_checking_imports = true` (imports inside `if TYPE_CHECKING:` guards are not flagged as R3 violations, since they are type-only references with no runtime dependency).
- A `layers` contract with the name `Clean architecture layers` and `layers = ["yascheduler.entrypoints", "yascheduler.infra", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`.
- Dev dependency pinned as `import-linter >=2.5,<2.6` (the upper bound is required because `import-linter 2.6+` dropped Python 3.9 support, and the project pins `python >=3.9`).

The `forbidden` contract (`Shared kernel has no config imports`) is removed
(see the REMOVED requirement above) — `yascheduler.config` no longer exists,
so the contract is vacuous.

#### Scenario: pyproject.toml contains required keys
- **WHEN** `pyproject.toml` is parsed
- **THEN** the `[tool.importlinter]` section contains `root_package`, `exclude_type_checking_imports`, and one `[[tool.importlinter.contracts]]` entry of type `layers` with `yascheduler.entrypoints` as the 1st layer and `yascheduler.shared` as the 5th layer; no `forbidden` contract entry exists

#### Scenario: TYPE_CHECKING imports not flagged
- **WHEN** a module in `yascheduler.application` contains an import under `if TYPE_CHECKING:` that references a symbol in `yascheduler.infra`
- **THEN** the `layers` contract does NOT report a violation (the import is type-only)

#### Scenario: Module-level imports still flagged
- **WHEN** a module in `yascheduler.application` contains a module-level import (not under `TYPE_CHECKING`) from `yascheduler.infra`
- **THEN** the `layers` contract reports a violation (unless covered by `ignore_imports`)

#### Scenario: import-linter version compatible with Python 3.9
- **WHEN** the dev environment installs with `python >=3.9`
- **THEN** `import-linter >=2.5,<2.6` is installed and `lint-imports` runs without Python-version errors, and the `layers` contract type is recognized