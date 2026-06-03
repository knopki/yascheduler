## Context

This change builds on `test-foundation` (pytest infra, directory structure, helpers). The target modules are:

- **Data models** (`db.py`): `TaskStatus` (IntEnum), `TaskModel`, `NodeModel` — attrs frozen dataclasses with a custom `__hash__` on `TaskModel`
- **Config modules** (`config/*.py`): 8 frozen attrs classes parsing INI sections via `from_config_parser_section` classmethods. Use `make_default_field` from `config/utils.py` for defaults with `default_if_none` converter. `Engine` has cross-field validators (`_check_spawn`, `_check_check_`).
- **DB class** (`db.py`): Async wrapper over `pg8000.native.Connection`. Methods construct SQL and map rows to models. `DB.run` uses `backoff.on_exception` and `run_in_executor`.

All config parsing goes through `configparser.SectionProxy`. The `Config.from_config_parser` top-level factory assembles all sub-configs.

## Goals / Non-Goals

**Goals:**
- Test data model construction, immutability, hashing, and `TaskStatus` enum semantics
- Test config parsing from INI strings for all sub-modules (defaults, overrides, validation errors)
- Test `DB` methods with mocked connection — verify correct SQL and parameter binding
- Create `FakeDB` reusable class matching the `DB` public interface

**Non-Goals:**
- Integration tests with real PostgreSQL (follow-up: `test-integration-db`)
- Testing `Scheduler`, `RemoteMachine`, or cloud modules (follow-up changes)
- Testing `compat.py`, `variables.py`, `time.py` (trivial modules, not worth dedicated tests)

## Decisions

### D1: Config tests use inline INI strings

Config test cases build `ConfigParser` from inline string literals rather than reading files from `tmp_path`. This is simpler and keeps test cases self-contained. Example:

```python
cfg = ConfigParser()
cfg.read_string("[db]\nuser=myuser\n[local]\n[remote]\n[clouds]\n")
```

### D2: DB unit tests mock at `pg8000.Connection` level

Mock `Connection.run` and `Connection.row_count` to verify SQL queries without a real database. Each test sets up mock return values (row tuples) and asserts on the SQL string and parameters passed to `run`.

`DB` is constructed directly with mocked objects — no need for the `create()` factory in tests:

```python
mock_conn = MagicMock(spec=Connection)
mock_conn.run = MagicMock(return_value=[...])
db = DB(loop=mock_loop, executor=mock_executor, conn=mock_conn)
```

### D3: FakeDB as attrs class with in-memory dict storage

`FakeDB` stores tasks and nodes in dicts, implements the same public methods as `DB` but operates purely in memory. Returns real `TaskModel`/`NodeModel` objects. Auto-increments `task_id`. Designed for scheduler unit tests in a future change.

### D4: Engine validation error tests cover cross-field validators

`Engine` has interesting validators: `_check_spawn` validates template placeholders, `_check_check_` ensures at least one check method is set, `_check_at_least_one_elem` requires non-empty `input_files`/`output_files`. These are worth testing for error messages.

## Risks / Trade-offs

- **DB mock tests verify SQL strings** — fragile if SQL is reformatted. Mitigate by testing behavior (correct params, correct model output) rather than exact string matching where possible.
- **Config parsing tests depend on INI format** — if INI format changes, tests break. This is desired: tests act as a safety net.
- **FakeDB may diverge from real DB** — if `DB` methods change, `FakeDB` must be updated. Mitigate by keeping `FakeDB` minimal and reviewing alongside DB changes.
