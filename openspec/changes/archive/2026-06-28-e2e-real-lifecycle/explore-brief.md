# Explore Brief — e2e-real-lifecycle

## Problem

`tests/e2e/test_full_cycle.py` is a fake E2E: one node, manual SSH connect, manual
DB writes bypassing `yasetnode`, direct `CLIDeps.submit` instead of `yasubmit`,
`make_daemon + orch.start()` instead of `daemonize`/`run_daemon`, manual
`uow.nodes.remove` instead of `yasetnode --remove-*`. Green test does NOT prove
the application works in even the simplest happy path.

## Goal

A real end-to-end test exercising actual entrypoint code paths (`_submit_async`,
`_manage_node_async`, `make_daemon` + `orch.start()`), multi-node scheduling, and
soft-remove via entrypoint — verifying the daemon actually schedules jobs onto
different nodes and that outputs are downloaded.

## Rejected alternatives

- **Subprocess CLI** (`uv run yasubmit ...`, `uv run yascheduler ...`): maximal
  realism but heavy infra (stdout parsing for task_id, signal handling for
  daemon stop, CWD isolation for yasubmit input-file reads). User explicitly
  approved calling internal async functions directly.
- **Hard-remove path**: only relevant for the edge case of abandoning RUNNING
  tasks. For our happy path (all tasks DONE before removal), soft-remove takes
  the `remove` branch cleanly. Asserting hard-remove behavior here is wrong
  scope.
- **Asserting exact 2:2 distribution**: nondeterministic by design — with
  ~3s tasks and 2 nodes, 1:3 / 2:2 / 3:1 are all valid. Only 0:4 / 4:0 indicate
  a broken node. Correct invariant: both node IPs appear in the allocated_ip set
  and neither carries all 4 tasks.
- **Waiting for both nodes to connect before submitting**: artificial
  serialization. Jobs can be submitted before nodes exist; the allocator
  producer cycles over TO_DO tasks every `sleep_interval` and the cloud path
  emits `[NO_PROVIDER]` debug logs when no free machines and no clouds. This
  is observable behavior worth tracking.
- **Refactoring `run_daemon` to add a signal-registration guard**: not needed
  because we call `make_daemon + orch.start()` directly, never `run_daemon`. No
  production-code changes are required for this change.

## Final approach — labels / mapping tables

### Entrypoints exercised (all via internal async functions, not subprocess)

| App action        | Internal async function called from test-loop        | Sync entrypoint skipped |
| ----------------- | ---------------------------------------------------- | ----------------------- |
| Submit task       | `_submit_async(argv)` from `entrypoints/cli/submit.py` | `submit()` = `asyncio.run(_submit_async)` |
| Add node          | `_manage_node_async(argv)` from `entrypoints/cli/manage_node.py` | `manage_node()` = `asyncio.run(_manage_node_async)` |
| Remove node (soft)| `_manage_node_async([host, "--remove-soft", ...])`    | same                    |
| Run daemon        | `make_daemon(config)` + `asyncio.create_task(orch.start())` | `daemonize()` / `run_daemon()` |

Rationale: skips only `asyncio.run` + `sys.exit(1)` error path. All real logic
(argparse parsing, INI load via `args.config`, `make_cli_deps`, UoW, SSH connect,
`setup_node`, `submit_task`, `allocate_task`, `consume_task`) is exercised.

### Test phases

1. Start daemon (`make_daemon` + `orch.start()` as background task).
2. Submit 4 jobs via `_submit_async` — each with temp script file (`ENGINE=test_shell`,
   `LABEL=job_N`) and temp CWD containing `1.input="hello e2e N"`. Capture `task_id`
   from stdout via `capfd`/`capsys` (the function prints `str(task_id)`).
3. Assert: all 4 tasks are TO_DO in DB.
4. (Optional, log-tracked) before nodes exist, allocator logs `[NO_PROVIDER]`.
5. Add node A via `_manage_node_async([hostA, "--config", ini])`.
6. Add node B via `_manage_node_async([hostB, "--config", ini])`.
7. Assert: `uow.nodes.list_all() == [A, B]`.
8. Poll DB: collect `(task_id, allocated_ip)` snapshot per cycle while tasks
   transition RUNNING; wait until all 4 reach DONE (timeout 30s).
9. Assert:
   - all 4 DONE, `context.error is None`
   - each output file `1.input.out` exists and content matches `hello e2e N`
   - distribution: `set(allocated_ip) == {ipA, ipB}` AND no single node got
     all 4 (reject 0:4 / 4:0; accept 1:3, 2:2, 3:1)
   - log records contain `[ALLOCATED] task_id=X ip=Y` for all 4 task_ids, with
     both IPs appearing
10. Remove node A via `_manage_node_async([hostA, "--remove-soft", "--config", ini])`.
11. Remove node B via `_manage_node_async([hostB, "--remove-soft", "--config", ini])`.
12. Assert: `uow.nodes.list_all() == []`.
13. Stop daemon in `finally`: `orch.stop()` + `wait_for(orch_task, timeout=10)`.

### Fixtures

| Fixture (scope)       | Purpose                                                                  |
| --------------------- | ------------------------------------------------------------------------ |
| `postgres_container` (session, exists) | real PostgreSQL via testcontainers                         |
| `ssh_pool` (session, NEW) | list of 2 SSH containers (linuxserver/openssh-server), ONE shared keypair, each yields `host_ip`/`port`/`username`/`key_path`. Both containers get the same `PUBLIC_KEY` env. |
| `e2e_config` (session, MODIFIED) | temp INI + `data/keys/<keyname>` symlink (one symlink, reused by both node connects) + `data/engines/test_shell/run.sh` (exists). `[remote] user = testuser`. No `[cloud.*]` sections. |
| `uow_factory` (function, exists) | per-test PostgresUnitOfWork; teardown TRUNCATE                  |
| `log_records` (function, NEW) | in-memory `logging.Handler` capturing all `yascheduler.*` records at DEBUG; attaches to root logger for the test, detaches in teardown. Used for log assertions. |

### SSH container separation

Each testcontainer `DockerContainer("lscr.io/linuxserver/openssh-server:10.2_p1-r0-ls222")`
exposes a distinct `get_container_host_ip()` and a distinct mapped port 2222.
The fixture starts 2 containers with the same `PUBLIC_KEY` and yields a list of
`{host, port, username, key_path}` dicts. `e2e_config` symlinks the single
keypair into `data/keys/` so `list_private_keys(config.local.keys_dir)` resolves
it for both `_add_node` calls.

### Log-tracking mechanism

`logging.Handler` subclass appends `LogRecord` to a list. Registered on the
`"yascheduler"` logger (propagation on) at DEBUG level for the test duration.
Assertions grep over `record.getMessage()` for substrings:
- `[Orchestrator][_allocator_producer] task_ids=` (producer cycling)
- `[AllocateTask][_try_allocate_to_machine][ALLOCATED] task_id=N ip=H` (per-task allocation)
- `[AllocateTask][allocate_task][NO_PROVIDER]` (pre-node phase, optional)

### ncpus semantics

Confirmed from code: `_start_task_on_machine` resolves
`ncpus = (node and node.ncpus) or await self._operations.get_cpu_cores(session)`.
`ncpus=0` (current test value) falsy-coerces to the real CPU count — no per-node
slot limit. Both nodes accept multiple concurrent tasks limited only by BUSY
state (set by `session.occupy()` in `_try_start_on_machine`, released by the
occupancy monitor when `pgrep check_pname` returns empty).

### Soft-remove semantics

Confirmed from `manage_node.py:222`: `_remove_node_soft` queries
`list_ids_by_ip_and_status(ip, RUNNING)`. Empty list (our case — all tasks DONE)
→ `uow.nodes.remove(ip)` + commit. Non-empty → `disable(ip)`. After our happy
path both nodes take the `remove` branch.

## Cross-module data flows

```
_test_ ── _submit_async(argv) ──▶ _parse_submit_args ──▶ parse_config
                                   └─▶ _parse_script_metadata
                                   └─▶ make_cli_deps(config)
                                   └─▶ _build_metadata (reads 1.input from cwd)
                                   └─▶ deps.submit → submit_task → uow.tasks.insert + save + commit
                                   └─▶ print(str(task_id))  # captured

_test_ ── _manage_node_async([host, "--config", ini]) ──▶ _parse_node_args
                                                            └─▶ parse_config
                                                            └─▶ make_cli_deps
                                                            └─▶ validation UoW (read-only)
                                                            └─▶ _add_node: SSHMachineRepository.connect + setup_node + uow.nodes.add + commit + disconnect

_test_ ── make_daemon(config) ──▶ Orchestrator(...)  # background task: orch.start()
        orch.start() ──▶ producer-consumers: connect_machine / allocate / consume / deallocate

_test_ ── _manage_node_async([host, "--remove-soft", ...]) ──▶ _remove_node_soft ──▶ uow.nodes.remove

_test_ ── uow_factory() ──▶ uow.tasks.get(task_id)  # polling for DONE + allocated_ip
```

## Open questions (none)

All ambiguities resolved during explore mode:
- entrypoint invocation mechanism — internal async functions, user-approved
- daemon start mechanism — `make_daemon + orch.start()`, user-approved
- distribution invariant — set-equality + reject-monopoly, not exact counts
- remove path — soft, user-specified
- ssh separation — different container IPs, one shared keypair

## OpenSpec impact

- `openspec/specs/e2e-testing/spec.md` — modify: replace the bypass-paths
  (lines 36, 41 prescribe `uow.nodes.add`/`uow.nodes.remove` directly) with
  entrypoint-path requirements; add multi-node + distribution + soft-remove +
  log-tracking scenarios.
- No new capabilities. No production-code changes.