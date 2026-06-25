## Context

`yascheduler/infra/ssh/platform/adapters.py` and `common.py` are two small files using `attrs` for simple class definitions. The project is incrementally migrating away from `attrs` toward stdlib `dataclasses`. These two files are isolated (no downstream code constructs the classes directly — tests use `MagicMock()`) and mechanically straightforward, making them ideal candidates.

## Goals / Non-Goals

**Goals:**
- Replace `attrs.define`/`evolve`/`field` with `dataclasses.dataclass`/`replace`/`field` in both files.
- Preserve exact same behavior: frozen/mutable semantics, field defaults, construction pattern.
- Update GRACE-lite metadata (FILE VERSION, CHANGE_SUMMARY, MODULE_MAP wording).

**Non-Goals:**
- Do NOT introduce `__slots__` (Python 3.9 min, singletons, marginal gain, precedent from queue.py avoids it).
- Do NOT add custom `__eq__`/`__hash__` — stdlib defaults match prior attrs behavior for both classes.
- Do NOT remove `attrs` from `pyproject.toml` — other modules still depend on it.
- Do NOT touch `yascheduler/infra/cloud/adapters.py`, `config/*`, or any other file.
- Do NOT change public API, CLI, config, DB schema, or test contracts.

## Decisions

### 1. Mechanical mapping: `adapters.py`

| Before (attrs) | After (stdlib dataclasses) |
|---|---|
| `from attrs import define, evolve, field` | `from dataclasses import dataclass, field, replace` |
| `@define(frozen=True)` | `@dataclass(frozen=True)` |
| `platform: str = field()` | `platform: str` |
| `path: type[PurePath] = field()` | `path: type[PurePath]` |
| `quote: QuoteCallable = field()` | `quote: QuoteCallable` |
| `run: RunCallable = field()` | `run: RunCallable` |
| `run_bg: RunBgCallable = field()` | `run_bg: RunBgCallable` |
| `get_cpu_cores: GetCPUCoresCallable = field()` | `get_cpu_cores: GetCPUCoresCallable` |
| `list_processes: ListProcessesCallable = field()` | `list_processes: ListProcessesCallable` |
| `pgrep: PgrepCallable = field()` | `pgrep: PgrepCallable` |
| `setup_node: SetupNodeCallable = field()` | `setup_node: SetupNodeCallable` |
| `checks: Sequence[SSHCheck] = field(factory=tuple)` | `checks: Sequence[SSHCheck] = field(default_factory=tuple)` |

The 9 `field()` calls with no args become bare annotations — `dataclasses.field()` with no args is redundant and less readable.

The `checks` field uses `factory=tuple` → `default_factory=tuple`. Tuple is immutable, safe as a default factory.

### 2. Mechanical mapping: `common.py`

| Before (attrs) | After (stdlib dataclasses) |
|---|---|
| `from attrs import define` | `from dataclasses import dataclass` |
| `@define` | `@dataclass` |
| `pid: int` | `pid: int` (unchanged) |
| `name: str` | `name: str` (unchanged) |
| `command: str` | `command: str` (unchanged) |

Trivial one-to-one substitution. No `field()` calls, no defaults, no `evolve()`.

### 3. 14 `evolve()` → `replace()` substitutions

All in `adapters.py`, constructing versioned singletons from base adapters:

From `linux_adapter`:
- `debian_like_adapter = replace(linux_adapter, platform="debian-like", checks=(*linux_adapter.checks, check_is_debian_like))`
- `debian_adapter = replace(debian_like_adapter, platform="debian", checks=(*debian_like_adapter.checks, check_is_debian))`
- `debian_10_adapter = replace(debian_adapter, platform="debian-10", checks=(*debian_adapter.checks, check_is_debian_10))`
- `debian_11_adapter = replace(debian_adapter, platform="debian-11", checks=(*debian_adapter.checks, check_is_debian_11))`
- `debian_12_adapter = replace(debian_adapter, platform="debian-12", checks=(*debian_adapter.checks, check_is_debian_12))`
- `debian_13_adapter = replace(debian_adapter, platform="debian-13", checks=(*debian_adapter.checks, check_is_debian_13))`
- `debian_14_adapter = replace(debian_adapter, platform="debian-14", checks=(*debian_adapter.checks, check_is_debian_14))`
- `debian_15_adapter = replace(debian_adapter, platform="debian-15", checks=(*debian_adapter.checks, check_is_debian_15))`
- `darwin_adapter = replace(linux_adapter, platform="darwin", checks=(check_is_darwin,))`

From `windows_adapter`:
- `windows7_adapter = replace(windows_adapter, platform="windows-7", checks=(*windows_adapter.checks, check_is_windows_7))`
- `windows8_adapter = replace(windows_adapter, platform="windows-8", checks=(*windows_adapter.checks, check_is_windows_8))`
- `windows10_adapter = replace(windows_adapter, platform="windows-10", checks=(*windows_adapter.checks, check_is_windows_10))`
- `windows11_adapter = replace(windows_adapter, platform="windows-11", checks=(*windows_adapter.checks, check_is_windows_11))`
- `windows12_adapter = replace(windows_adapter, platform="windows-12", checks=(*windows_adapter.checks, check_is_windows_12))`

`functools.replace()` is semantically identical to `attrs.evolve()` for frozen dataclasses — creates a new instance with overridden fields.

### 4. No `__slots__` added

- Python minimum is 3.9; `slots=True` for dataclasses requires 3.10+.
- `RemoteMachineAdapter` has 15 module-level singleton instances — slots provide no meaningful memory saving.
- `ProcessInfo` is yielded in async generator streams — marginal benefit, not worth the compat complexity.
- The `queue.py` precedent explicitly avoided `__slots__`.

### 5. No custom `__eq__`/`__hash__`

Stdlib defaults for `@dataclass(frozen=True)` produce `__eq__` comparing all fields and `__hash__` based on all fields (because frozen=True enables hashing). This matches prior `attrs @define(frozen=True)` behavior.

For mutable `@dataclass` (ProcessInfo), stdlib `__eq__` compares all fields, `__hash__` is `None` (mutable, not hashable) — matches `attrs @define` behavior.

### 6. `attrs` dependency stays

After this change, `attrs` is still imported in:
- `yascheduler/config/cloud.py`, `remote.py`, `db.py`, `local.py`, `engine.py`, `engine_repository.py`, `config.py`, `utils.py`
- `yascheduler/infra/cloud/cloud_config.py`, `adapters.py`, `manager.py`, `protocols.py`
- `yascheduler/infra/cloud/providers/az.py`

Do NOT remove `attrs>=22.2.0` from `pyproject.toml`.

## Risks / Trade-offs

- **Risk**: `replace()` requires all non-overridden fields to be present and valid. Same constraint as `evolve()`. No regression risk.
- **Risk**: Import ordering or circular import if `replace` is imported lazily. Mitigation: `replace` is resolved at definition time (same as `evolve`), and both files are leaf modules with no circular dependency.
- **Trade-off**: Keeping `attrs` as a dependency means the project has two active class-definition systems. Acceptable — this is incremental cleanup, not a comprehensive migration.
