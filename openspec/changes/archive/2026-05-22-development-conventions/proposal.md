## Why

The project has no formalized development conventions. Rules about Python version, tooling, public interface stability, and dependency management are scattered across AGENTS.md and tribal knowledge. A spec-level document ensures all contributors follow the same rules without ambiguity.

## What Changes

- Add `development-conventions` spec: a single authoritative document capturing development rules.
- Replace pyright with zuban for type checking (remove `pyright` from dev deps, remove `[tool.pyright]` from pyproject.toml).
- Establish the "public interface stability" rule: any change to CLI, Library API, Config format, DB schema, or AiiDA entrypoint requires explicit declaration in the change proposal.
- Establish the "no new dependencies without intent" rule.

## Capabilities

### New Capabilities

- `development-conventions`: Rules governing Python version, tooling, public interface stability, dependency management, package manager compatibility, methodology, and version management.

### Modified Capabilities

(none — no existing specs to modify)

## Impact

- `pyproject.toml`: remove pyright from dev deps, remove `[tool.pyright]` section, add zuban to dev deps.
- `AGENTS.md`: references to pyright will become outdated; may need minor sync.
- All future change proposals: must declare public interface changes if any.
