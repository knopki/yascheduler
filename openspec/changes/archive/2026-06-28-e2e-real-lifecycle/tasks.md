## 1. Fixtures

- [x] 1.1 Add `ssh_pool` session-scoped fixture to `tests/e2e/conftest.py`: generate ONE `asyncssh.generate_private_key("ssh-rsa")` keypair, start TWO `DockerContainer("lscr.io/linuxserver/openssh-server:10.2_p1-r0-ls222")` instances with the same `PUBLIC_KEY` env and `USER_NAME`, each with exposed port 2222 and `LogMessageWaitStrategy("sshd is listening")`. Yield a list of two dicts `{host, port, username, key_path}` with distinct `host` values (container IPs) and identical `key_path`/`username`. Stop both containers in `finally`.
- [x] 1.2 Update `e2e_config` fixture in `tests/e2e/conftest.py` to consume `ssh_pool` (instead of `ssh_container`); keep the single keypair symlink in `data/keys/`. INI content unchanged (`[db]`, `[local]`, `[remote] user = testuser`, `[engine.test_shell]`). Remove the now-unused `ssh_container` fixture (or keep it as a thin wrapper returning `ssh_pool[0]` for backward compat with `test_consume_retry.py` — prefer the wrapper to avoid touching `test_consume_retry.py`).
- [x] 1.3 Add `log_records` function-scoped fixture to `tests/e2e/conftest.py`: a `LogCaptureHandler(logging.Handler)` subclass that appends each `LogRecord` to a list; attach to the `"yascheduler"` logger at DEBUG level on setup, remove on teardown. Yield the list of records.
- [x] 1.4 Verify `test_consume_retry.py` still resolves its `ssh_container` fixture (either via the wrapper from 1.2 or by updating its signature to `ssh_pool` and indexing `[0]`).

## 2. Rewrite test_full_cycle.py

- [x] 2.1 Replace `tests/e2e/test_full_cycle.py` with the new entrypoint-driven test skeleton: imports (`_submit_async`, `_manage_node_async`, `make_daemon`, `monkeypatch`), test signature `async def test_full_cycle(e2e_config, uow_factory, ssh_pool, log_records, monkeypatch, tmp_path, capfd)`.
- [x] 2.2 Implement step "Start daemon": `orchestrator = await make_daemon(e2e_config); orch_task = asyncio.create_task(orchestrator.start())` wrapped in a `try/finally` that calls `orchestrator.stop()` + `asyncio.wait_for(orch_task, timeout=10)` with `except (asyncio.CancelledError, asyncio.TimeoutError): orch_task.cancel()` (matching the pattern in `test_consume_retry.py`).
- [x] 2.3 Implement step "Submit 4 jobs": for N in 1..4, create a temp script file with `ENGINE=test_shell\nLABEL=job_N`, create a temp CWD with `1.input` containing `"hello e2e N"`, `monkeypatch.chdir(cwd)`, call `_submit_async([str(script), "--config", str(ini_path)])`, capture `task_id` from stdout via `capfd` (or `contextlib.redirect_stdout`), assert `task_id > 0`, restore CWD. Collect the 4 `task_id`s.
- [x] 2.4 Implement step "Assert queued": open a UoW, read each task by id, assert all four have `status == DomainTaskStatus.TO_DO`.
- [x] 2.5 Implement step "Add 2 nodes": for each of the two `ssh_pool` entries, call `_manage_node_async([entry["host"], "--config", str(ini_path)])`. Assert `uow.nodes.list_all()` returns both nodes (compare IPs).
- [x] 2.6 Implement step "Wait for completion": poll loop (up to 30s, 0.5s sleep) reading each task via `uow_factory`; collect `(task_id, allocated_ip)` snapshots when tasks are `RUNNING`; break when all four are `DONE`.
- [x] 2.7 Implement step "Assert completion and outputs": for each task, assert `status == DONE`, `context.error is None`, `context.local_folder` set, and `Path(local_folder)/"1.input.out"` exists with content `"hello e2e N"` matching the per-job payload.
- [x] 2.8 Implement step "Assert distribution": `ips = {t.allocated_ip for t in tasks}; assert ips == {ipA, ipB}`; reject monopoly: `for ip in (ipA, ipB): assert sum(1 for t in tasks if t.allocated_ip == ip) < 4`.
- [x] 2.9 Implement step "Assert scheduling activity in logs": grep `log_records` for `record.getMessage()` containing `[AllocateTask][_try_allocate_to_machine][ALLOCATED]` — assert one record per `task_id` and that both node IPs appear in the logged `ip=` substrings.
- [x] 2.10 Implement step "Remove nodes (soft)": for each node, call `_manage_node_async([host, "--remove-soft", "--config", str(ini_path)])`. Assert `uow.nodes.list_all()` is empty.
- [x] 2.11 Add GRACE-lite markup to the test file: update `FILE`, `VERSION`, `START_MODULE_CONTRACT` (PURPOSE: "E2E test exercising full scheduler lifecycle via real entrypoint code paths across two SSH nodes"), `START_MODULE_MAP`, `START_CHANGE_SUMMARY` (LAST_CHANGE: this change), and per-block `START_BLOCK_*` / `END_BLOCK_*` anchors matching the test phases.

## 3. Spec update

- [x] 3.1 The delta spec `openspec/changes/e2e-real-lifecycle/specs/e2e-testing/spec.md` is already written — verify it still matches the final test implementation after tasks 1–2 (no drift). Fix any drift declaratively (typos, scenario wording) without touching decision-level content.
- [x] 3.2 Run `openspec validate --all --json` and confirm ALL VALID.

## 4. GRACE-lite & validation

- [x] 4.1 Update `tests/e2e/conftest.py` GRACE-lite markup: bump `VERSION`, update `START_MODULE_MAP` to list the new `ssh_pool` and `log_records` fixtures, add a `START_CHANGE_SUMMARY` entry for this change.
- [x] 4.2 Run `python3 scripts/grace_check.py` and confirm exit 0.
- [x] 4.3 Run `uv run ruff check .` and `uv run ruff format --check .` and `uv run lint-imports`; fix any issues in the changed test files only.
- [x] 4.4 Run `uv run pytest -m e2e tests/e2e/test_full_cycle.py -x` and confirm the new test passes. If it fails, debug and fix the test (NOT production code — if production code is the root cause, stop and surface it).
- [x] 4.5 Run `uv run pytest -m e2e tests/e2e/ -x` and confirm `test_consume_retry.py` still passes (the `ssh_container`/`ssh_pool` fixture change must not break it).