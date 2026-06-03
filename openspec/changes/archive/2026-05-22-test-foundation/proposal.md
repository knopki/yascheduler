## Why

The project has zero tests. Any refactoring or feature work carries high risk of silent regressions. Establishing a testing infrastructure is prerequisite for all future changes.

## What Changes

- Add pytest infrastructure: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock`, `testcontainers[postgres]`
- Configure pytest in `pyproject.toml` (asyncio mode, markers, testpaths)
- Create `tests/` directory structure split by level: `unit/`, `integration/`, `e2e/`
- Create shared conftest fixtures and test data helpers
- Write initial unit tests for `queue.py` (UniqueQueue) to validate the infrastructure works
- Add CI workflow for running unit tests on every push

## Capabilities

### New Capabilities
- `testing-infrastructure`: pytest configuration, directory structure, dependency declarations, conftest fixtures, test data helpers
- `testing-ci`: GitHub Actions workflow for automated test execution

### Modified Capabilities
_(none — no existing specs change)_

## Impact

- `pyproject.toml`: new dependencies in `[dependency-groups].dev`, new `[tool.pytest.ini_options]` section
- New `tests/` directory tree (not shipped with the package)
- `.github/workflows/`: new CI workflow file
- No changes to production code
