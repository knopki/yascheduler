## Why

Integration tests cover DB and SSH gateway in isolation, but no test exercises the full scheduler lifecycle: node registration → engine deployment → task submit → allocate → spawn → occupancy detection → output download → task completion → node removal. This gap means integration bugs between orchestrator, SSH gateway, DB, and engine deployment can escape CI.

## What Changes

- Add a new E2E test in `tests/e2e/` that runs the complete scheduler cycle against real PostgreSQL (testcontainers) and real SSH server (testcontainers `openssh-server` container).
- Add a test engine (`test_shell`) consisting of a shell script (`run.sh`) deployed via `LocalFilesDeploy`, which sleeps briefly then copies `1.input` to `1.input.out`.
- Add E2E fixtures: session-scoped PostgreSQL + SSH containers, function-scoped config with temp directory, generated INI file, SSH key setup, engine script, and orchestrator wiring.
- The test uses programmatic API calls (`_add_node`, `deps.submit`, `make_daemon`) rather than subprocess CLI, exercising the same code paths as CLI entry points.

## Capabilities

### New Capabilities
- `e2e-testing`: End-to-end test infrastructure and full-cycle test that validates the scheduler's complete task lifecycle against real PostgreSQL and SSH containers.

### Modified Capabilities
- `testing-infrastructure`: E2E test directory already exists with marker conftest; no spec-level requirement changes needed.

## Impact

- New files: `tests/e2e/conftest.py` (fixtures), `tests/e2e/test_full_cycle.py` (test), engine script under temp dir created by fixtures.
- No changes to production code.
- CI: E2E tests run only explicitly (`pytest tests/e2e/`), not in default CI workflow.
- Dependencies: reuses existing testcontainers (postgres, openssh-server), asyncssh.
