## 1. Fixtures

- [x] 1.1 Create `tests/e2e/conftest.py` with session-scoped `postgres_container` fixture (reuse pattern from `tests/integration/conftest.py`)
- [x] 1.2 Add session-scoped `ssh_container` fixture (reuse pattern from `tests/integration/test_ssh_gateway.py`)
- [x] 1.3 Add session-scoped `e2e_config` fixture: create temp dir, generate minimal INI (`[db]` + `[engine.test_shell]`), create `data/engines/test_shell/run.sh`, symlink SSH key into `data/keys/`, set `YASCHEDULER_CONF_PATH`, parse and yield `Config`
- [x] 1.4 Add session-scoped `_init_schema` fixture to apply schema.sql once
- [x] 1.5 Add function-scoped `db` fixture with TRUNCATE teardown (same pattern as integration)

## 2. Test Engine

- [x] 2.1 Create `run.sh` content in the `e2e_config` fixture: `#!/bin/sh\nsleep 3\ncat 1.input > 1.input.out`, make executable

## 3. Full Cycle Test

- [x] 3.1 Create `tests/e2e/test_full_cycle.py` with `test_full_cycle` function
- [x] 3.2 Implement phase 1 (add node): create `RemoteMachine`, call `setup_node(engines)`, insert node via UoW
- [x] 3.3 Implement phase 2 (submit task): call `deps.submit("e2e test", {"1.input": "hello e2e"}, "test_shell")`
- [x] 3.4 Implement phase 3 (run orchestrator): create via `make_daemon`, start as async task
- [x] 3.5 Implement phase 4 (poll completion): poll `db.get_task(task_id)` until `DONE` with 30s timeout
- [x] 3.6 Implement phase 5 (verify output): check downloaded `1.input.out` content
- [x] 3.7 Implement phase 6 (cleanup): stop orchestrator, remove node from DB

## 4. Verification

- [x] 4.1 Run `pytest tests/e2e/test_full_cycle.py -v` and confirm test passes
- [x] 4.2 Run `uv run ruff check tests/e2e/` and `uv run ruff format --check tests/e2e/` — no issues
