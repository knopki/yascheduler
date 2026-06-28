## Context

The current `tests/e2e/test_full_cycle.py` (v1.4.0) and `tests/e2e/conftest.py`
(v2.2.0) together provide a single-node, bypass-path test that passes green
while calling none of the application's real entrypoint code. The OpenSpec spec
`openspec/specs/e2e-testing/spec.md` explicitly prescribes the bypass
(`uow.nodes.add` / `uow.nodes.remove` directly, lines 36 and 41), so the test
and the spec must be rewritten together.

The application entrypoints are sync wrappers of the form
`def f(argv): asyncio.run(_f_async(argv))` over async cores
(`_submit_async`, `_manage_node_async`, `run_daemon`). The async cores do all the
real work (argparse, INI load, UoW, SSH, submit_task, allocate_task,
consume_task). The daemon lifecycle has `run_daemon(config, logger)` which
registers SIGTERM/SIGINT handlers on the running loop — undesirable inside a
pytest loop — so the test uses `make_daemon(config)` +
`asyncio.create_task(orch.start())` directly, which is the production code path
minus signal handlers.

Constraints:
- No production-code changes. All test realism is achieved by calling the
  internal async functions from the test's event loop.
- Python ≥ 3.9 (per `pyproject.toml`); `asyncio.run` cannot nest, so sync
  entrypoint wrappers are unreachable from an async test — this is the only
  reason we skip them.
- `yasubmit` reads input files from `os.getcwd()` (`_build_metadata` in
  `entrypoints/cli/submit.py`), so each `_submit_async` call needs a
  per-invocation CWD with the `1.input` file. We use `monkeypatch.chdir` per
  call.
- The orchestrator's allocator producer cycles over TO_DO tasks every
  `sleep_interval` (1s for the test_shell engine) regardless of whether free
  machines exist; with no free machines and no configured clouds,
  `allocate_task` logs `[NO_PROVIDER]` and returns False — the task stays TO_DO
  and is retried next cycle. This is the observable "waiting for nodes" state.
- The orchestrator's `_find_free_machines` sorts free sessions by
  `free_since` (oldest first) and `_try_start_on_machine` calls
  `session.occupy()` synchronously, raising `MachineBusyError` on a race. The
  allocator consumer's `except Exception` wrap logs the error and the task is
  retried next producer cycle — the system self-heals.

## Goals / Non-Goals

**Goals:**
- A single E2E test in `tests/e2e/test_full_cycle.py` that proves the daemon
  schedules 4 jobs across 2 real SSH containers via the actual entrypoint code
  paths, downloads outputs, and removes nodes cleanly via the soft-remove path.
- All entrypoint logic exercised: argparse, INI parsing, `make_cli_deps`,
  `setup_node`, `submit_task`, `allocate_task`, `consume_task`, `_remove_node_soft`.
- Observable scheduling activity via collected daemon debug logs.
- Updated `openspec/specs/e2e-testing/spec.md` reflecting the entrypoint-driven
  lifecycle and multi-node scenarios.
- Reusable `ssh_pool` (session) and `log_records` (function) fixtures for future
  E2E tests.

**Non-Goals:**
- Testing the sync wrappers `submit()` / `manage_node()` / `daemonize()` — they
  are one-line `asyncio.run` shims; exercising them would require subprocess
  invocation which the user explicitly rejected for this change.
- Testing `run_daemon`'s signal-handler registration path — out of scope; the
  test calls `make_daemon` + `orch.start()` directly.
- Testing cloud provisioning — there are no `[cloud.*]` sections in the test
  INI; the allocator's `[NO_PROVIDER]` path is observed but not asserted as a
  hard requirement (it is a side-effect of submitting before nodes exist).
- Testing hard-remove (`--remove-hard`) — that path is for abandoning RUNNING
  tasks; our happy path has all tasks DONE before removal, so soft-remove takes
  the `remove` branch. Hard-remove remains covered by unit tests.
- Refactoring production code to make sync entrypoints testable from an async
  loop. If that becomes desirable later, it is a separate change.
- Asserting exact task distribution counts (2:2). Distribution is
  nondeterministic; only set-equality `{ipA, ipB}` and rejection of 0:4 / 4:0
  are asserted.

## Decisions

### D1: Invoke entrypoints via internal async functions, not subprocess

**Choice:** Call `_submit_async(argv)` and `_manage_node_async(argv)` directly
from the test loop.

**Rationale:** The sync wrappers are `def f(argv): asyncio.run(_f_async(argv))`.
`asyncio.run` cannot be called from a running loop, so the wrappers are
unreachable from an async test without spinning a separate thread with its own
loop (which the user explicitly rejected as too heavy). The async cores execute
100% of the real logic: argparse parsing (`_parse_submit_args`,
`_parse_node_args`), INI loading (`parse_config`), `make_cli_deps`, validation
UoW reads, SSH connect + `setup_node`, `submit_task`, `uow.nodes.add` /
`uow.nodes.remove` + commit, and the `sys.exit(1)` error path (not hit on happy
path). The only code skipped is `asyncio.run` itself and the `sys.exit(1)`
error branch.

**Alternatives considered:**
- Subprocess `uv run yasubmit ...` / `uv run yasetnode ...`: maximal realism but
  requires parsing task_id from stdout, CWD isolation per subprocess, and a
  signal-based daemon stop. User rejected.
- Refactor sync wrappers to raise typed exceptions instead of `sys.exit(1)`:
  would let the test call the sync wrappers via `asyncio.to_thread`. Out of
  scope (production-code change). Rejected for this change.

### D2: Start daemon via `make_daemon` + `orch.start()`, not `run_daemon`

**Choice:** `orchestrator = await make_daemon(config); orch_task =
asyncio.create_task(orchestrator.start())`. Stop in `finally` via
`orchestrator.stop()` + `asyncio.wait_for(orch_task, timeout=10)`.

**Rationale:** `run_daemon(config, logger)` calls `loop.add_signal_handler` for
SIGTERM/SIGINT, which raises `RuntimeError` outside the main thread and is
undesirable in a pytest loop even in the main thread (signal handlers would
interfere with pytest's own signal handling). `make_daemon` + `orch.start()` is
the exact production path minus signal registration — the orchestrator's
producer-consumer loops, connect-machine path, allocator, consumer, and
deallocator are all exercised. The existing `test_full_cycle.py` and
`test_consume_retry.py` already use this pattern successfully.

**Alternatives considered:**
- Add a `register_signals: bool = True` parameter to `run_daemon` and call it
  with `register_signals=False`. Production-code change; out of scope. The
  current approach is already established in the existing tests.
- Subprocess `yascheduler --config INI` + `proc.terminate()`. Heavy; requires
  log-file plumbing; user rejected.

### D3: Submit jobs BEFORE adding nodes

**Choice:** Submit all 4 jobs first, assert they are TO_DO, then add the two
nodes.

**Rationale:** This is the realistic operator flow (queue work, then provision
capacity) AND it lets the test observe the allocator's `[NO_PROVIDER]` debug
log entries while no machines are connected — a side-effect that confirms the
producer is cycling. It also avoids any artificial synchronization on
"wait until both nodes are connected" — the orchestrator naturally picks up the
queued tasks on the first allocator cycle after the nodes connect.

**Alternatives considered:**
- Add nodes first, wait for `_await_first_machine`, then submit: serializes the
  test and hides the no-provider spin behavior. User explicitly rejected
  ("Зачем добавлять ноды и ЖДАТЬ ПОДКЛЮЧЕНИЯ? Ждать подключения 100% не нужно").

### D4: Distribution invariant — set equality + reject monopoly

**Choice:** Assert `set(allocated_ip for t in tasks) == {ipA, ipB}` and that no
single node received all 4 tasks (reject 0:4 and 4:0). Do NOT assert `count == 2`
per node.

**Rationale:** The test_shell engine's `run.sh` sleeps 3s. With 2 nodes and 4
tasks, the first two tasks occupy both nodes (~3s BUSY); the next two are
scheduled as nodes free up. Depending on timing jitter, the split can be 1:3,
2:2, or 3:1. Only 0:4 / 4:0 indicate a broken node (one never accepted a task).
User explicitly specified this invariant.

**Alternatives considered:**
- Assert `count == 2` per node: flaky and wrong. Rejected by user.
- Assert only set equality: insufficient — a 4:0 split would still pass. The
  monopoly-rejection clause is required.

### D5: Soft-remove, not hard-remove

**Choice:** Both nodes removed via
`_manage_node_async([host, "--remove-soft", "--config", ini])`.

**Rationale:** After all 4 tasks are DONE, `_remove_node_soft` queries
`list_ids_by_ip_and_status(ip, RUNNING)` (empty list in our happy path) and
takes the `uow.nodes.remove(ip)` branch — the clean delete path. Hard-remove
(`_remove_node_hard`) is for abandoning RUNNING tasks and is out of scope.
User explicitly specified soft-remove.

**Alternatives considered:**
- Hard-remove: wrong scope (RUNNING-task abandonment). Rejected by user.

### D6: Two SSH containers sharing one keypair

**Choice:** `ssh_pool` session fixture starts two
`DockerContainer("lscr.io/linuxserver/openssh-server:10.2_p1-r0-ls222")`
instances with the same `PUBLIC_KEY` env (generated once via
`asyncssh.generate_private_key("ssh-rsa")`). Each yields its own
`get_container_host_ip()` and mapped port 2222. `e2e_config` symlinks the single
private key into `data/keys/` so `list_private_keys(config.local.keys_dir)`
resolves it for both `_add_node` calls.

**Rationale:** testcontainers assigns each container a distinct host IP (on
Linux, typically the docker bridge IP). One shared keypair avoids key-management
complexity and mirrors the real operator workflow (one key, many machines).

**Alternatives considered:**
- Two keypairs, two symlinks: more fixtures, no added realism. Rejected.
- Distinguish containers by port only (one host, two mapped ports): the user
  explicitly said "ssh контейнеры проще разделять не по портам, а по ip адресам
  (они у контейнеров разные)" — different container IPs is cleaner.

### D7: Log tracking via in-memory `logging.Handler`

**Choice:** A `LogCaptureHandler(logging.Handler)` appends every `LogRecord` to a
list. The `log_records` function fixture attaches it to the `"yascheduler"`
logger at DEBUG level for the test duration and detaches in teardown. The test
greps `record.getMessage()` for substrings like
`[AllocateTask][_try_allocate_to_machine][ALLOCATED] task_id=N ip=H`.

**Rationale:** The orchestrator and allocate/consume use cases already emit
structured block-boundary debug logs with the task_id and ip embedded. An
in-memory handler is cheaper than parsing a log file and integrates cleanly
with pytest fixtures. Capturing at the `"yascheduler"` logger (with propagation)
catches all sub-loggers (`yascheduler.application.*`, `yascheduler.infra.*`).

**Alternatives considered:**
- `configure_logger(log_file=path, level=DEBUG)` + read the file post-hoc:
  works but requires a temp file and post-hoc parsing. In-memory is simpler.
- pytest's `caplog` fixture: captures at the root logger by default; works but
  requires `propagate=True` and level config. A dedicated handler on
  `"yascheduler"` is more targeted and predictable.

### D8: CWD isolation for `_submit_async`

**Choice:** Each of the 4 `_submit_async` calls runs under a
`monkeypatch.chdir(temp_cwd_for_job)` context, where `temp_cwd_for_job` contains
a `1.input` file with the job's payload (`"hello e2e N"`).

**Rationale:** `_build_metadata` in `entrypoints/cli/submit.py` calls
`_read_input_files(engine, os.getcwd())` — the input file is read from the
current working directory at submit time. Without per-invocation CWD isolation,
all 4 jobs would read the same `1.input` (whichever was chdir'd last),
collapsing the per-job payload distinction. `monkeypatch.chdir` auto-restores
the original CWD on teardown.

**Alternatives considered:**
- Refactor `_submit_async` to accept a `cwd` parameter: production-code change;
  out of scope.
- Write a single `1.input` and accept identical payloads for all 4 jobs: loses
  the per-job content assertion ("hello e2e N" → "hello e2e"). Weakens the test.

## Risks / Trade-offs

- **[Risk] `_submit_async` / `_manage_node_async` raise `SystemExit(1)` on
  error.** → Mitigation: happy path does not hit `sys.exit(1)`; the test asserts
  stdout contains a task_id and the DB row exists. If an error path is hit, the
  `SystemExit` propagates through the test as a failure — acceptable signal.
- **[Risk] testcontainers SSH container startup latency.** Two containers add
  ~5-10s to the session-scoped fixture. → Mitigation: session scope amortizes
  across all e2e tests; acceptable.
- **[Risk] Distribution timing jitter.** Even with the set-equality invariant,
  a pathological run could land 4:0 if one node is slow to connect. →
  Mitigation: assert `uow.nodes.list_all() == [A, B]` AFTER both `_add_node`
  calls return, and the connect-machine producer retries static nodes
  indefinitely (the `STATIC_NODE_RETRY` path never abandons). Both nodes will be
  connected before the allocator can place all 4 tasks. The 4:0 case would
  indicate a real bug, not jitter.
- **[Risk] `monkeypatch.chdir` + async test.** `os.chdir` is process-global; if
  the orchestrator's background tasks read CWD, they could observe a transient
  wrong CWD. → Mitigation: the orchestrator does not read CWD; all paths come
  from `config`. The chdir window is only the duration of the synchronous
  `_submit_async` call. Acceptable.
- **[Risk] Log-capture handler leaks across tests.** → Mitigation: the
  `log_records` fixture removes the handler in teardown (yield-and-cleanup or
  `addfinalizer`).
- **[Risk] Soft-remove while a task is still RUNNING.** → Mitigation: the test
  polls until all 4 tasks are DONE before issuing soft-remove; the
  `_remove_node_soft` query for RUNNING tasks will be empty.
- **[Trade-off] Skipping sync wrappers means a regression in `asyncio.run`
  wiring or `sys.exit` error formatting would not be caught.** Accepted — these
  are one-line shims with no branching; unit tests for the wrapper layer are
  sufficient.

## Migration Plan

No migration. This is a test-only change. The old `test_full_cycle.py` is
replaced wholesale; the old `conftest.py` fixtures remain and two new fixtures
are added. The `e2e-testing` spec is rewritten in place. No DB schema, config,
or runtime behavior changes.

Rollback: `git revert` the change commit. No data or state to restore.

## Open Questions

None. All design decisions were resolved during explore mode and confirmed by
the user.