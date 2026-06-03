## Context

yascheduler has no test suite. The project is async-first (asyncio + asyncssh + aiohttp), uses PostgreSQL via pg8000, and interacts with cloud APIs and SSH machines. The codebase has clear module boundaries documented in `docs/knowledge-graph.xml`.

Current stack: Python 3.9+, attrs, pg8000, asyncssh, aiohttp. Build tooling: uv, ruff, zuban.

## Goals / Non-Goals

**Goals:**
- Establish pytest as the test framework with async support
- Define a three-level test structure: unit / integration / e2e
- Default `pytest` runs only unit tests (no external services)
- Validate infrastructure by shipping unit tests for `queue.py`
- Provide shared fixtures and test data helpers for future tests
- Run unit tests in CI on every push

**Non-Goals:**
- Writing tests for modules beyond `queue.py` (follow-up changes)
- Integration or e2e tests (follow-up changes)
- Coverage gates or enforcement
- SSH or cloud testcontainers (future work)
- Changes to production code

## Decisions

### D1: pytest with pytest-asyncio, mode=auto

`pytest-asyncio` with `asyncio_mode = "auto"` — all async test functions run on an event loop without explicit markers. The project is fully async; this removes boilerplate.

### D2: Directory-based level separation

```
tests/
├── unit/          ← testpaths default
├── integration/
├── e2e/
├── conftest.py    ← shared fixtures
└── fixtures/      ← test data helpers
```

Levels are directories, not markers. `testpaths = ["tests/unit"]` in pyproject.toml makes `pytest` run only unit by default. Integration/e2e invoked explicitly: `pytest tests/integration/`.

Markers (`@pytest.mark.unit`, `.integration`, `.e2e`) exist as metadata only — useful for selective runs like `pytest -m integration` but not the primary filtering mechanism.

### D3: All test dependencies in `[dependency-groups].dev`

Single group. `testcontainers[postgres]` is not heavy enough to warrant a separate group. Everything installed with `uv sync --group dev`.

### D4: Test data helpers as plain functions

Simple `make_task(**overrides)`, `make_node(**overrides)` functions in `tests/fixtures/models.py`. attrs frozen dataclasses + defaults make factory_boy unnecessary at this scale (2 models).

### D5: Protocol-based fakes for recurring mocks, unittest.mock for one-offs

Modules with stable protocol contracts (DB, RemoteMachine, CloudAPI) get reusable fake classes when needed in future changes. One-off stubs use `pytest-mock` / `AsyncMock`. Not building fakes in this change — just establishing the convention.

### D6: CI runs unit tests only

GitHub Actions workflow triggers on push/PR, runs `pytest` (unit only via testpaths), `ruff check`, `ruff format --check`, `zuban check`. No integration/e2e in CI yet.

## Risks / Trade-offs

- **testcontainers requires Docker** → integration tests won't run without Docker installed. Acceptable: integration is opt-in, unit tests are the default.
- **pytest-asyncio auto mode** may cause surprises with async fixtures → document in conftest if issues arise.
- **No coverage gate** → coverage is informational only. Risk of undetected gaps. Acceptable at this stage; gates added later when coverage baseline exists.
