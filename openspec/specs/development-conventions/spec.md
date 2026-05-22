## Purpose

Rules governing Python version, tooling, public interface stability, dependency management, package manager compatibility, methodology, and version management for the yascheduler project.

## Requirements

### Requirement: Python version constraint
The project SHALL declare `requires-python = ">=3.9"` in pyproject.toml. Changing the minimum Python version SHALL be treated as a breaking change requiring explicit declaration in a change proposal.

#### Scenario: Python version is declared
- **WHEN** pyproject.toml is read
- **THEN** `requires-python` is set to `">=3.9"`

#### Scenario: Minimum version change requires proposal
- **WHEN** a contributor wants to change the minimum Python version
- **THEN** a change proposal SHALL declare this as a public interface change

### Requirement: Project validated by linters
The project SHALL use ruff for formatting and linting, zuban for type checking, `openspec validate` for OpenSpec validatation, `.agents/skills/grace-lite/scripts/grace_check.py` for GRACE-lite validation.

#### Scenario: Python code is changed
- **WHEN** Python code is changed
- **THEN** `uv run ruff check .` SHALL pass
- **AND** `uv run zuban check` SHALL pass
- **AND** `.agents/skills/grace-lite/scripts/grace_check.py` SHALL pass

#### Scenario: Knowledge Graph is changed
- **WHEN** `docs/knowledge-graph.xml` is changed
- **THEN** `.agents/skills/grace-lite/scripts/grace_check.py` SHLL pass

#### Scenario: OpenSpec specification is changed 
- **WHEN** OpenSpec specification is changed
- **THEN** `openspec validate --all --json` SHALL pass

### Requirement: No new dependencies without intent
Dependencies SHALL NOT be added to pyproject.toml unless the change proposal explicitly states the dependency addition and its rationale.

#### Scenario: Dependency added without proposal
- **WHEN** a change adds a new dependency without declaring it in the proposal
- **THEN** the change SHALL be rejected

#### Scenario: Dependency added with proposal
- **WHEN** a change proposal explicitly declares a new dependency with rationale
- **THEN** the dependency MAY be added to pyproject.toml

### Requirement: Public interface stability
The following public interfaces SHALL NOT be modified without explicit declaration in the change proposal:

- **CLI commands**: `yasubmit`, `yastatus`, `yanodes`, `yasetnode`, `yainit`, `yascheduler` — names, arguments, and semantics
- **Library API**: `class Yascheduler` — all public methods and class attributes
- **Configuration format**: INI format parsed by configparser, including `[engine.*]` dynamic sections and `%(key)s` interpolation
- **Database schema**: `schema.sql` tables and `db.py` migrations — any schema change SHALL include a migration
- **AiiDA entrypoint**: `aiida.schedulers = yascheduler` entry point name

#### Scenario: CLI command renamed without proposal
- **WHEN** a change renames or removes a CLI command without declaring it
- **THEN** the change SHALL be rejected

#### Scenario: Yascheduler public method signature changed with proposal
- **WHEN** a change proposal declares a public method signature change
- **THEN** the method MAY be modified as described in the proposal

#### Scenario: Database schema changed without migration
- **WHEN** a change modifies schema.sql without a corresponding migration
- **THEN** the change SHALL be rejected

#### Scenario: Config format changed with proposal
- **WHEN** a change proposal declares a configuration format change
- **THEN** the format MAY be modified as described in the proposal

### Requirement: Package manager compatibility
The project SHALL maintain compatibility with both pip and uv. pyproject.toml SHALL NOT use tool-specific features that break compatibility with the other tool.

#### Scenario: pyproject.toml uses PEP 621 standard
- **WHEN** pyproject.toml is read
- **THEN** it uses standard PEP 621 fields without tool-specific build requirements

### Requirement: GRACE-lite methodology
GRACE-lite methodology SHALL be followed when working with source files. This includes module contracts, navigation through knowledge-graph.xml, and validation.

#### Scenario: Source file is modified
- **WHEN** a source file is created or modified
- **THEN** GRACE-lite contracts and markers SHALL be maintained

### Requirement: OpenSpec methodology
OpenSpec methodology SHALL be followed for behavioral changes. Changes to code, configuration, CLI, workflows, engine contracts, cloud behavior, DB schema, or operational behavior SHALL consult `openspec/specs/` before implementation.

#### Scenario: Behavioral change without spec consultation
- **WHEN** a change modifies behavior without checking relevant specs
- **THEN** the change SHALL be flagged for review

### Requirement: Version managed by automation
The project version in pyproject.toml SHALL NOT be edited manually. Version management is owned by commitizen and release automation.

#### Scenario: Version is not hand-edited
- **WHEN** a contributor modifies pyproject.toml
- **THEN** the version field is not changed by hand
