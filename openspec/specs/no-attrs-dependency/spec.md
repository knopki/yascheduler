# No Direct Attrs Dependency

## Purpose

yascheduler has no direct runtime dependency on the `attrs` package. All record
types in `yascheduler/` are stdlib `dataclasses.dataclass` (frozen unless
mutability is required by a documented invariant). A CI-guard canary test fails
if any module under `yascheduler/` imports `attrs` or `attr`. Transitive
presence of `attrs` via third-party packages (notably `aiohttp`) in `uv.lock`
is expected and out of scope.
## Requirements
### Requirement: No direct attrs dependency

The `[project].dependencies` array in `pyproject.toml` SHALL NOT list `attrs`.
All record types defined under `yascheduler/` SHALL be stdlib
`dataclasses.dataclass` instances; no module under `yascheduler/` SHALL import
`attrs` or `attr` at runtime or under a `TYPE_CHECKING` guard.

A canary test `tests/unit/test_no_attrs_dependency.py` SHALL walk every `.py`
file under `yascheduler/`, parse it with `ast`, and fail if any `ImportFrom`
or `Import` node targets a module name starting with `attrs` or `attr`. The
canary guards production code only; `tests/` is excluded. The canary flags
`TYPE_CHECKING`-guarded attrs imports as well — `attrs` is a runtime
third-party package, not a typing shim, and must not appear in any yascheduler
module's import graph in any form.

`attrs` MAY remain in `uv.lock` as a transitive dependency of `aiohttp` (and
other third-party packages). The canary test does not inspect `uv.lock` or
third-party package internals; it guards only the `yascheduler/` package's own
import graph.

#### Scenario: pyproject.toml does not list attrs

- **WHEN** `pyproject.toml` is parsed and the `[project].dependencies` array is inspected
- **THEN** the array does not contain the string `attrs` (in any form: `attrs`, `attrs>=...`, `attrs~=...`, etc.)

#### Scenario: canary test guards reintroduction

- **WHEN** a contributor adds `from attrs import define` (or `import attrs`, or `from attr import ...`, or any import targeting a module starting with `attrs` or `attr`) to any `.py` file under `yascheduler/`
- **THEN** `tests/unit/test_no_attrs_dependency.py::test_no_attrs_imports_in_yascheduler` fails on the next `uv run pytest -m unit` run, with a message listing the offending file and import node

#### Scenario: canary test passes on a clean tree

- **WHEN** `uv run pytest -m unit tests/unit/test_no_attrs_dependency.py` is run on a tree where no `yascheduler/` module imports `attrs` or `attr`
- **THEN** the canary test passes

#### Scenario: TYPE_CHECKING-guarded attrs import is also flagged

- **WHEN** a contributor adds `if TYPE_CHECKING: from attrs import Attribute` to a module under `yascheduler/`
- **THEN** the canary test fails (the import is flagged regardless of the `TYPE_CHECKING` guard context, because `attrs` is a runtime package and has no place in yascheduler's import graph)

#### Scenario: transitive attrs via aiohttp is allowed

- **WHEN** `uv.lock` is inspected
- **THEN** `attrs` appears as a transitive dependency of `aiohttp` (and may appear under other third-party packages); the canary test does not inspect `uv.lock` and does not fail because of transitive presence

#### Scenario: attrs remains importable in the environment

- **WHEN** `uv run python -c "import attrs"` is executed in the project environment
- **THEN** it succeeds (the package is transitively resolvable via `aiohttp`); removing the direct dependency does not break third-party code that relies on `attrs` being importable

#### Scenario: yascheduler imports remain clean

- **WHEN** `grep -rn "from attrs\|import attrs" yascheduler/` is executed
- **THEN** it returns no import statements — only `CHANGE_SUMMARY` comment lines that historically mention "attrs" (e.g. `# LAST_CHANGE: ... Migrate ... from attrs.define ...`). Those comment matches are expected and are not a failure: the AST-based canary (`test_no_attrs_imports_in_yascheduler`) is the authoritative guard, and it ignores comments entirely. A clean tree is one where the canary passes, not one where the grep returns zero textual matches.

