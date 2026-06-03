## 1. Dependencies and Configuration

- [x] 1.1 Add test dependencies to `[dependency-groups].dev` in `pyproject.toml`: `pytest~=8.0`, `pytest-asyncio~=0.25`, `pytest-cov~=6.0`, `pytest-mock~=3.0`, `testcontainers[postgres]~=4.0`
- [x] 1.2 Add `[tool.pytest.ini_options]` section to `pyproject.toml` with `asyncio_mode = "auto"`, `testpaths = ["tests/unit"]`, and marker definitions for `unit`, `integration`, `e2e`
- [x] 1.3 Run `uv sync --group dev` and verify `pytest --co` works

## 2. Test Directory Structure

- [x] 2.1 Create `tests/` directory with `unit/`, `integration/`, `e2e/` subdirectories, each containing `__init__.py`
- [x] 2.2 Create `tests/fixtures/` directory with `__init__.py`

## 3. Shared Fixtures and Helpers

- [x] 3.1 Create `tests/conftest.py` with shared fixtures
- [x] 3.2 Create `tests/fixtures/models.py` with `make_task()` and `make_node()` helper functions

## 4. Unit Tests for queue.py

- [x] 4.1 Create `tests/unit/test_queue.py` covering: put/get, deduplication, item_done tracking, psize, task_done NotImplementedError

## 5. CI Workflow

- [x] 5.1 Create `.github/workflows/test.yml` running on push/PR: Python 3.9, `uv sync --group dev`, `ruff check .`, `ruff format --check .`, `zuban check`, `pytest`
