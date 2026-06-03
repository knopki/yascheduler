## Context

The project has unit tests (mocked everything), integration tests (real PostgreSQL + real SSH container, but tested separately), and an empty `tests/e2e/` directory. The orchestrator's producer-consumer loop — connecting machines, allocating tasks, spawning processes, detecting completion, downloading results — has never been tested end-to-end against real infrastructure.

The existing integration fixtures (`postgres_container`, `ssh_container`, `db`, `gateway`) provide building blocks, but the E2E test needs its own config and orchestrator wiring.

## Goals / Non-Goals

**Goals:**
- Validate the full scheduler lifecycle: node add → engine deploy → task submit → allocate → spawn → occupancy detect → download → task done → node remove
- Test engine deployment (`LocalFilesDeploy` → SFTP upload → remote execution) with a real shell script
- Exercise `Orchestrator` producer-consumer loops against real SSH + real PostgreSQL
- Reuse existing testcontainers infrastructure (PostgreSQL, openssh-server)

**Non-Goals:**
- Cloud provider testing (no real cloud API calls)
- Multi-node or multi-engine scenarios (single node, single engine)
- Performance or load testing
- Testing CLI subprocess invocation (we call the same functions programmatically)
- AiiDA plugin testing

## Decisions

### D1: Programmatic API calls, not subprocess CLI

Call `_add_node`, `deps.submit`, `make_daemon` directly. The CLI entry points (`yasetnode`, `yasubmit`, `daemonize`) are thin wrappers around these functions. Programmatic calls give us: better error messages, easier fixture wiring, no need to parse stdout.

### D2: Minimal INI config (only `[db]` + `[engine.test_shell]`)

`Config.from_config_parser` auto-adds empty `[local]`, `[remote]`, `[clouds]` sections with sensible defaults. With `cwd` set to the temp directory, `data_dir` resolves to `tmp_path/data`, giving us `engines_dir`, `keys_dir`, `tasks_dir` for free. No need to specify them in INI.

### D3: Test engine as a shell script (`run.sh`)

```
#!/bin/sh
sleep 3
cat 1.input > 1.input.out
```

Deployed via `deploy_local_files = run.sh`. This validates the entire deployment pipeline: `deploy_local_files` → SFTP `put` → remote `chmod +x` (handled by `preserve=True`) → `{engine_path}/run.sh` spawn.

### D4: Poll DB for task completion

Wait for task status to become `DONE` by polling `db.get_task(task_id)` in a loop with timeout (e.g., 30s). Simpler and more reliable than parsing DEBUG logs. The alternative — capturing log messages — is fragile and couples the test to log format.

### D5: `YASCHEDULER_CONF_PATH` env var for config discovery

The `variables.py` module reads `YASCHEDULER_CONF_PATH` env var. Set it in the fixture to point at the generated INI. This means `Config.from_config_parser(CONFIG_FILE)` in `utils.py` and `client.py` picks up the test config automatically.

### D6: Reuse SSH container pattern from integration tests

Same `lscr.io/linuxserver/openssh-server` image, same key generation pattern. Session-scoped to avoid per-test container startup overhead. The key is symlinked into `tmp_path/data/keys/` so `config.local.get_private_keys()` finds it.

### D7: Empty `[clouds]` section → `CloudAPIManager` with no APIs

No mocking needed. `CloudAPIManager.create()` with empty `cloud_configs` produces a manager with no adapters. `clouds.allocate()` and `clouds.mark_task_done()` are no-ops.

## Risks / Trade-offs

- **Timing sensitivity**: The orchestrator runs async loops with `sleep_interval`. Test may be slow (3s sleep in run.sh + orchestrator cycles). → Keep sleep intervals minimal (sleep_interval=1, run.sh sleep=3). Use generous timeout (30s) for polling.
- **Container startup overhead**: Two testcontainers per session (~5-10s). → Session-scoped fixtures amortize cost across all E2E tests.
- **SSH container quirks**: The `linuxserver/openssh-server` container has specific home directory layout. Remote paths (`data_dir`, `engines_dir`) must be writable by `testuser`. → Default remote paths (`./data/...`) resolve relative to home dir, which is writable.
- **Test order dependency**: Orchestrator consumes from DB. If other tests leave data, could interfere. → Function-scoped `db` fixture with TRUNCATE teardown (same pattern as integration tests).
