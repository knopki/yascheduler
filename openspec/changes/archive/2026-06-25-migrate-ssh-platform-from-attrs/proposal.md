## Why

Reduce `attrs` usage surface in the SSH subsystem. The project has a stated direction to migrate off `attrs` toward stdlib `dataclasses` (precedent: `UMessage` in `application/queue.py` v1.8.0; FIXME comments in `infra/cloud/adapters.py:28` and `config/config.py:21`). Two files in `yascheduler/infra/ssh/platform/` use `attrs` for simple struct/dataclass patterns — they are the easiest, lowest-risk candidates for migration.

## What Changes

- Replace `attrs.define`/`evolve`/`field` with `dataclasses.dataclass`/`replace`/`field` in exactly two files:
  - `yascheduler/infra/ssh/platform/adapters.py` — `RemoteMachineAdapter` class (frozen dataclass, 10 fields, 14 `evolve()` calls for versioned singletons)
  - `yascheduler/infra/ssh/platform/common.py` — `ProcessInfo` class (mutable struct, 3 fields)
- No public API, CLI, config, DB schema, or behavior changes.
- No change to `pyproject.toml` — `attrs` remains a project dependency for other modules.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is a pure refactor with no REQUIREMENTS-level behavior change. The `platform-adapters` spec is unaffected — implementation details (attrs vs dataclasses) are below the spec threshold.

## Impact

- **Affected code**: `yascheduler/infra/ssh/platform/adapters.py`, `yascheduler/infra/ssh/platform/common.py`
- **Dependencies**: No additions or removals. `attrs>=22.2.0` stays in `pyproject.toml`.
- **Tests**: Zero impact — tests mock adapters via `MagicMock()` and never construct `RemoteMachineAdapter` directly.
- **GRACE-lite**: FILE VERSION bumps and CHANGE_SUMMARY updates in both files; `common.py` MODULE_MAP wording update ("Attrs struct" → "dataclass struct"); knowledge graph untouched (private-only change).
