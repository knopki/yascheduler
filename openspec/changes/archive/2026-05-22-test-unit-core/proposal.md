## Why

The `test-foundation` change establishes pytest infrastructure but only tests `queue.py`. The next layer of test coverage targets pure data models, configuration parsing, and the DB layer — the modules that everything else depends on and that are cheap to test.

## What Changes

- Add unit tests for `TaskStatus`, `TaskModel`, `NodeModel` (frozen attrs dataclasses in `db.py`)
- Add unit tests for all config sub-modules: `ConfigDb`, `ConfigLocal`, `ConfigRemote`, cloud configs (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `AzureImageReference`), `Engine`, `EngineRepository`
- Add unit tests for `Config.from_config_parser` (top-level config assembly)
- Add unit tests for `DB` methods with mocked `pg8000.Connection` — verifying SQL queries, parameter binding, and result mapping
- Create a `FakeDB` protocol-compatible class for reuse in scheduler/orchestration tests (future change)

## Capabilities

### New Capabilities
- `test-data-models`: Unit tests for `TaskStatus`, `TaskModel`, `NodeModel` frozen attrs dataclasses
- `test-config-parsing`: Unit tests for INI → frozen config parsing across all sub-modules
- `test-db-unit`: Unit tests for `DB` class with mocked pg8000, verifying SQL and result mapping

### Modified Capabilities
_(none)_

## Impact

- New test files in `tests/unit/`: `test_models.py`, `test_config.py`, `test_db.py`
- New test helper: `tests/fixtures/fake_db.py` (FakeDB protocol-compatible class)
- No changes to production code
