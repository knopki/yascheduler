## Why

The `config/` package uses `attrs` for all configuration dataclasses. While
functional, this is the last remaining use of attrs in the codebase (domain
migrated to stdlib dataclasses in Phase 1). Removing it eliminates a
dependency and creates consistency.

## What Changes

- Replace `@attr.s(auto_attribs=True, frozen=True)` with `@dataclass(frozen=True)`
  in all config modules (`config.py`, `db.py`, `local.py`, `remote.py`,
  `cloud.py`, `engine.py`, `engine_repository.py`).
- Replace `attr.ib()` / `attr.field()` with `dataclasses.field()`.
- Replace `make_default_field()` (from `config/utils.py`) with stdlib
  `field(default_factory=...)`.
- Replace `evolve()` with `dataclasses.replace()`.
- No functional change — config parsing behavior identical.

## Capabilities

### New Capabilities
- `config-dataclasses`: Config package uses stdlib dataclasses instead of attrs.

## Impact

- Modified: all files in `yascheduler/config/`.
- No API changes. No behavior changes.
- `attrs` dependency remains in `pyproject.toml` (still used by old TaskModel/NodeModel,
  removed when those are migrated).
