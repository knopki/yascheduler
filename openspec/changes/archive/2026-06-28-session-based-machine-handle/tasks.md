## 1. Predecessor check & scaffolding

- [x] 1.1 Confirm `cleanup-unused-repository-symbols` is archived (its delta specs sync'd into `openspec/specs/ssh-machine-repository/spec.md` and `openspec/specs/domain-ports/spec.md`). If not archived yet, STOP — this change cannot proceed.
- [x] 1.2 Confirm the post-cleanup `SSHMachineRepository` no longer exposes `get_conn`, `get_adapter`, `get_platforms`, `get_data_dir`, `get_engines_dir`, `get_tasks_dir`, `keys`, `items`, `register_machine` (deleted by predecessor).
- [x] 1.3 Create empty `yascheduler/infra/ssh/session.py` with FILE/VERSION/MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY GRACE-lite headers (STATUS: planned).

## 2. Introduce `MachineSession` Protocol and `SSHMachineSession` concrete class

- [x] 2.1 Add `MachineSession` Protocol to `yascheduler/domain/ports.py` with the full surface from `ssh-machine-session` spec requirement "MachineSession port" — domain face (`ip`, `machine`, `is_closed`, `occupy`, `release`, `update`), connect-time config properties (`adapter`, `platforms`, `data_dir`, `engines_dir`, `tasks_dir`), adapter-derived (`path`, `quote`, `hostname`), base primitives (`run`, `run_full`, `run_bg`, `upload`, `open_sftp`, `get_cpu_cores`, `setup_node`, `pgrep`, `list_processes`), monitor mechanism (`install_monitor`, `cancel_monitor`). Mark `@runtime_checkable`. Do NOT declare `_close` (private to concrete class).
- [x] 2.2 Re-export `MachineSession` from `yascheduler/domain/__init__.py`.
- [x] 2.3 Implement concrete `SSHMachineSession` core in `yascheduler/infra/ssh/session.py`:
  - Constructor takes `ip`, `conn`, `conn_opts`, `machine` (initial snapshot), `adapter`, `platforms`, `data_dir`, `engines_dir`, `tasks_dir`, optional `log`. Stores `_closed = False`, `_monitor_task = None`.
  - Domain-face properties and methods (`ip`, `machine`, `is_closed`, `occupy`, `release`, `update`).
  - Connect-time-config read-only properties.
  - Adapter-derived properties (`path` → `adapter.path`, `quote` → `adapter.quote`, `hostname` → `conn_opts.host`).
  - Move `my_backoff_exc` canonical copy here from `operations/base.py`.
- [x] 2.4 Implement `SSHMachineSession` base primitives (`run`, `run_full`, `run_bg`, `upload`, `open_sftp`, `get_cpu_cores`, `setup_node`, `pgrep`, `list_processes`) using `self._conn` and `self._adapter` directly — NO repository call, NO IP-keyed lookup. `run_full` decorated with `@my_backoff_exc()`. `setup_node` uses `make_run_fn(conn, adapter)` from `infra/ssh/platform/run_fn.py`.
- [x] 2.5 Implement `SSHMachineSession` monitor mechanism + lifecycle:
  - `install_monitor(*, interval, check_factory, on_free)` ported from the post-cleanup `SSHMachineRepository` (Engine-agnostic shape preserved; identity-checked done-callback; cancels prior task before installing new). Returns early if `_closed`.
  - `cancel_monitor()` — pops and cancels (no await).
  - `_close()` coroutine: idempotency guard (`if self._closed: return`); set `self._closed = True` synchronously; cancel `_monitor_task`; await it (suppressing `CancelledError`); close conn if transport open and await `wait_closed()`.
- [x] 2.6 Add START_CONTRACT / START_BLOCK semantic markup per GRACE-lite: contract on `SSHMachineSession` class; contracts on `install_monitor`, `cancel_monitor`, `_close`, `occupy`, `release`, `update`, `run_full`, `setup_node`; blocks for `_CLOSE_*`, `_MONITOR_*` per current `repository.py` style.
- [x] 2.7 Run `python3 scripts/grace_check.py` to confirm new file passes XML + source checks.

## 3. Rewrite `SSHMachineRepository`

- [x] 3.1 Replace internal state shape: `_machines: dict[str, _MachineState]` → `_sessions: dict[str, SSHMachineSession]` in `SSHMachineRepository.__init__`. Drop `_monitors: dict[str, asyncio.Task[None]]` entirely. Delete `_MachineState` dataclass. Delete `_get_machine_state`.
- [x] 3.2 Rewrite connection lifecycle:
  - `_connect_impl` constructs `SSHMachineSession(ip=ip, conn=conn, conn_opts=conn_opts, machine=machine, adapter=adapter, platforms=platforms, data_dir=rd, engines_dir=re, tasks_dir=rt, log=self._log)` and stores in `_sessions[ip]`. Returns the session.
  - `connect` signature in Protocol and impl returns `MachineSession` (was `ConnectedMachine`).
  - `disconnect(ip)`: `session = self._sessions.pop(ip, None); if session is None: return; await session._close()`. Remove direct `_monitors.pop`, `task.cancel`, `await task`, `conn.close`, `await conn.wait_closed` — these now live in `session._close()`.
  - `disconnect_all` stays as `for ip in list(self._sessions): await self.disconnect(ip)`.
- [x] 3.3 Rewrite queries:
  - `list_free(platforms)`: iterate `_sessions.values()`, filter on `s.machine.state == FREE` and `s.machine.platform`, sort by `s.machine.free_since`. Return `list[MachineSession]`.
  - `list_connected()`: return `list(self._sessions.values())`. Return type `list[MachineSession]`.
  - `get_session(ip) -> MachineSession | None` returning `self._sessions.get(ip)`. Delete `get_machine_state`.
  - `contains`, `__contains__`, `__len__` unchanged.
- [x] 3.4 Delete migrated wrappers and mechanism:
  - Delete `occupy(ip)`, `release(ip)`, `update_machine(machine)` — these now live on `SSHMachineSession`.
  - Delete `get_path(ip)`, `get_quote(ip)`, `get_hostname(ip)` — these now live on `SSHMachineSession` as properties.
  - Delete `install_monitor(ip, ...)`, `cancel_monitor(ip)` — these now live on `SSHMachineSession`.
  - Delete `register_machine`, `keys`, `items` (test-only hooks; tests will poke `_sessions[ip] = session` directly).
- [x] 3.5 Update the `MachineRepository` Protocol in `domain/ports.py` to match: 9-method surface (`connect`, `disconnect`, `disconnect_all`, `list_free`, `list_connected`, `get_session`, `contains`, `__contains__`, `__len__`). Add MODIFIED note that previous accessor/wrapper/monitor methods are removed (migrated to `MachineSession`).
- [x] 3.6 Keep `MySSHClient`, `DEFAULT_CONN_OPTS`, `_resolve_tunnel` in `repository.py` — used by `_open_connection`. Add a comment marking them as connection-building bits that stay.
- [x] 3.7 Update repository MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY to reflect the new role (true collection only).
- [x] 3.8 Run `uv run pytest -m unit` for any tests that don't yet touch the changed code, to confirm no import errors. Expect many failures in `tests/unit/test_ssh_gateway*.py` — those are fixed in section 7.

## 4. Rewrite `SSHMachineOperations` facade

- [x] 4.1 Update `SSHMachineOperations.__init__(repository, log)` — keep the signature. Compose three collaborators as `TaskDeployer(log)`, `OutputDownloader(log)`, `OccupancyChecker(log)` (no repository/operations refs).
- [x] 4.2 Delete base primitives from `SSHMachineOperations` (`run`, `run_full`, `run_bg`, `upload`, `get_sftp`, `pgrep`, `list_processes`, `get_cpu_cores`, `setup_node`). They live on `SSHMachineSession` now.
- [x] 4.3 Delete narrow local Protocols (`CommandExecutor`, `SftpProvider`, `StateAccessors`) and the canonical `my_backoff_exc` (moved to `session.py`).
- [x] 4.4 Add facade pass-through methods on `SSHMachineOperations` per the `MachineOperations` Protocol: `run(session, cmd) → session.run(cmd)`, `run_full(session, cmd) → session.run_full(cmd)`, `run_bg(session, cmd, *, cwd=None) → session.run_bg(cmd, cwd=cwd)`, `get_cpu_cores(session) → session.get_cpu_cores()`, `setup_node(session, engines) → session.setup_node(engines)`.
- [x] 4.5 Update `start_task_on_machine(session, engine, task, ncpus, engines_dir)` to forward to `self.deploy.start_task_on_machine(session, engine, task, ncpus, engines_dir)`.
- [x] 4.6 Update `download_outputs(session, remote_dir, local_dir, files, task_id=None)` to forward to `self.download.download_outputs(session, remote_dir, local_dir, files, task_id)`.
- [x] 4.7 Update `occupancy_check(session, config)` to forward to `self.occupancy.occupancy_check(session, config)`.
- [x] 4.8 Update `start_occupancy_check(session, config)` to forward to `self.occupancy.start_occupancy_check(session, config)`.
- [x] 4.9 Update `MachineOperations` Protocol in `domain/ports.py` to declare the use-case methods + facade pass-throughs per the `ssh-machine-repository` spec delta requirement "MachineOperations port". All machine-reference parameters typed `session: MachineSession`.
- [x] 4.10 Update MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY on `operations/base.py` (facade-only now; primitives moved out).

## 5. Rewrite collaborators as stateless

- [x] 5.1 `TaskDeployer.__init__(log)` — drop `operations` and `repository` parameters.
- [x] 5.2 `TaskDeployer.start_task_on_machine(session, engine, task, ncpus, engines_dir)`:
  - Replace `self._repository.occupy(ip)` → `session.occupy()`.
  - Replace `self._repository.get_hostname(machine.ip)` → `session.hostname` (in the log message).
  - Replace `self._repository.get_path(machine.ip)` → `session.path`.
  - Replace `self._repository.get_quote(machine.ip)` → `session.quote`.
  - Replace `self._operations.get_sftp(ip)` → `session.open_sftp()`.
  - Replace `self._operations.run_bg(machine, cmd, cwd=…)` → `session.run_bg(cmd, cwd=…)`.
  - In the rollback `except BaseException` branch: replace `state = self._repository._get_machine_state(ip); if state is None: log "already disconnected"; raise` with `if session.is_closed: self._log.warning("...already disconnected..."); raise`. **Preserve the intermediate unexpected-state warning** (`if state.machine.state != MachineState.BUSY: log warning`) by reading `session.machine.state` — same behavior, session-based read. Replace `self._repository.update_machine(state.machine.release())` with `session.update(session.machine.release())`.
- [x] 5.3 `OutputDownloader.__init__(log)` — drop `operations` and `repository` parameters.
- [x] 5.4 `OutputDownloader.download_outputs(session, remote_dir, local_dir, files, task_id=None)`:
  - Replace `self._operations.get_sftp(ip)` → `session.open_sftp()`.
  - Replace `self._repository.get_path(ip)` → `session.path`.
  - Update any other IP-keyed references to use the session.
- [x] 5.5 `OccupancyChecker.__init__(log)` — drop `operations` and `repository` parameters.
- [x] 5.6 `OccupancyChecker._occupancy_by_pgrep(session, pattern)`: replace `self._operations.pgrep(ip, pattern)` → `session.pgrep(pattern)`. Adjust the async-for over the session's generator.
- [x] 5.7 `OccupancyChecker._occupancy_by_cmd(session, cmd, expected_code)`: replace `machine = self._repository.get_machine_state(ip); if machine is None: return True; proc = await self._operations.run_full(machine, cmd)` with `proc = await session.run_full(cmd)`.
- [x] 5.8 `OccupancyChecker.occupancy_check(session, config)`: dispatch on `config.check_pname`/`config.check_cmd` — pass `session` to the helpers.
- [x] 5.9 `OccupancyChecker.start_occupancy_check(session, config)`:
  - Replace `state = self._repository._get_machine_state(ip); if state.machine.state == FREE: self._repository.occupy(ip)` with `if session.machine.state == FREE: session.occupy()`.
  - Replace `self._repository.install_monitor(ip, interval=…, check_factory=…, on_free=partial(self._repository.release, ip))` with `session.install_monitor(interval=config.sleep_interval, check_factory=lambda: self.occupancy_check(session, config), on_free=session.release)`.
- [x] 5.10 Update MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY on each of `deployment.py`, `download.py`, `occupancy.py` to reflect stateless shape.

## 6. Update application-layer consumers

- [x] 6.1 `application/orchestrator.py` — producer/stats/dealloc methods:
  - `_print_stats`: `for s in self._repository.list_connected(): if s.machine.state == MachineState.BUSY: ...`
  - `_connect_machine_producer`: `not self._repository.contains(n.ip)` — unchanged signature.
  - `_allocator_producer`: `len(self._repository.list_free(None))` — unchanged (returns list, len works).
  - `_deallocator_producer`: `for s in self._repository.list_connected(): if s.machine.state == FREE and s.machine.free_since is not None: idle_machines[s.machine.ip] = s.machine.free_since`.
  - `_deallocator_consumer`: `self._repository.contains(ip)` and `self._repository.disconnect(ip)` — unchanged. `deallocate_node(node, self._repository, …)` — unchanged.
  - `stop`: `await self._repository.disconnect_all()` — unchanged.
- [x] 6.2 `application/orchestrator.py` — consumer methods (the per-tick session resolution):
  - `_task_consumer_consumer`: replace `machine = self._repository.get_machine_state(ip)` with `session = self._repository.get_session(ip); machine = session.machine if session is not None else None`. Apply the same pattern at line 470 (the re-read).
  - `_task_consumer_consumer`: replace `self._operations.start_occupancy_check(ip, engine)` with resolving session then `self._operations.start_occupancy_check(session, engine)`.
  - `_task_consumer_consumer`: `consume_task` call — pass `session` through (or have `consume_task` resolve via `repository.get_session`).
  - `_start_task_on_machine`: change parameter from `machine: ConnectedMachine` to `session: MachineSession`. `ncpus = await self._operations.get_cpu_cores(session)`; `await self._operations.start_task_on_machine(session, engine, task, ncpus, …)`. Update the call site at `_allocator_consumer` (line 394) to pass session instead of machine.
- [x] 6.3 `application/allocate_task.py`:
  - Update `start_task_on_machine` callback type from `Callable[[ConnectedMachine, Engine, Task], Awaitable[bool]]` to `Callable[[MachineSession, Engine, Task], Awaitable[bool]]` in `_try_start_on_machine` and `_allocate_free_machine` signatures.
  - Iterate `repository.list_free(...)` returning sessions; pick one, pass to `start_task_on_machine` callback.
  - The `operations.start_occupancy_check(machine.ip, engine)` call becomes `operations.start_occupancy_check(session, engine)` (use the picked session).
- [x] 6.4 `application/consume_task.py`: update `operations.download_outputs(ip, ...)` to resolve session first then pass it. Update any IP-keyed operations call sites.
- [x] 6.5 `application/deallocate_nodes.py`: signature unchanged (uses `repository.contains` and `repository.disconnect` — both preserved). Verify no other call site needs change.
- [x] 6.6 `application/abandon_node.py`: no SSH-side call — verify no change needed.
- [x] 6.7 `infra/cloud/manager.py`:
  - `connected_machine = await self.machine_repository.connect(...)` → rename local to `session` (it's a `MachineSession` now); `session.machine` is the snapshot where needed.
  - `self.machine_operations.run(connected_machine, ...)` → `self.machine_operations.run(session, ...)`.
  - `await self.machine_operations.setup_node(ip_addr, self.engines)` and `ncpus = await self.machine_operations.get_cpu_cores(ip_addr)`: resolve via the `session` already in hand from connect (preferred — avoids re-lookup); pass session to both methods.
  - `stop()`: `await self.machine_repository.disconnect_all()` — unchanged.
- [x] 6.8 `entrypoints/cli/check_status.py`:
  - Line 340: replace `repository._get_machine_state(ip)` (with `# noqa: SLF001`) with `repository.get_session(ip)`. Remove the noqa.
  - `_download_convergence_snippet` and `_display_remote_output`: collapse the `(repository, operations, ip)` triple-threaded helpers to take a single `MachineSession` (resolved once at the top of the command). Update the 4-tuple return shape of `_display_remote_output` accordingly.
  - The `repository.get_path(ip)` and `operations.get_sftp(ip)` calls (line 250-251) become `session.path` and `session.open_sftp()`.
- [x] 6.9 `entrypoints/cli/manage_node.py`: audit and update any IP-keyed operations call to resolve session first.
- [x] 6.10 `entrypoints/di.py`: verify construction unchanged (still wires `repository, operations` into Orchestrator). `SSHMachineOperations(repository=repository, log=log)` continues to work — the constructor signature is preserved; the implementation now constructs stateless collaborators internally. No code change expected unless test fake surface changes require updates.

## 7. Update tests

- [x] 7.1 `tests/unit/test_domain_ports.py`:
  - Add `FakeMachineSession` covering the full `MachineSession` Protocol surface.
  - Update `FakeMachineRepository` to return `FakeMachineSession` from `connect`/`list_free`/`list_connected`/`get_session`. Remove `get_machine_state`, `occupy`, `release`, `update_machine`, `get_path`, `get_quote`, `get_hostname`, `install_monitor`, `cancel_monitor`, `_get_machine_state`.
  - Update `FakeMachineOperations` method signatures to take `FakeMachineSession`.
- [x] 7.2 `tests/unit/test_ssh_gateway.py`:
  - Update fixtures: where they construct `_MachineState` and call `register_machine` or poke `repository._machines`, switch to constructing `SSHMachineSession` (via test helper or by calling `SSHMachineRepository.connect` against a fake conn) and poking `repository._sessions[ip] = session`.
  - Remove tests for removed methods (already mostly done by `cleanup-unused-repository-symbols`).
  - `test_get_machine_state_*` → `test_get_session_*` returning `MachineSession | None`.
  - `list_free` / `list_connected` assertions: read `session.machine.state` / `session.machine.platform` etc.
  - Add `test_fresh_session_is_not_closed`: after `connect`, assert `session.is_closed is False`.
- [x] 7.3 `tests/unit/test_ssh_gateway_machine_queries.py`:
  - Rename `_get_machine_state` tests to `get_session` tests.
  - `_get_machine_state("10.0.0.1") is state` → `get_session("10.0.0.1") is session`.
- [x] 7.4 `tests/unit/test_ssh_gateway_bg_tasks.py` (the four monitor invariants — R2):
  - Replace every `repository._machines[ip] = ...` with `repository._sessions[ip] = ...`.
  - Replace every `repository._monitors[ip]` reference: monitors now live on `session._monitor_task`. Tests that asserted on `_monitors` shape now assert on `session._monitor_task` identity (e.g., the done-callback identity check that compared `_monitors[ip] is task` becomes `session._monitor_task is task`), or assert behaviorally (e.g., "after disconnect, no monitor callback fires").
  - The four invariants (disconnect-scope isolation, prior-monitor replacement, identity-checked done-callback, pop-before-await ordering) MUST be re-expressed as new behavioral test names that don't depend on the old dict shape.
- [x] 7.5 `tests/unit/test_ssh_gateway_retry_rollback.py` (R1):
  - Replace `repository._machines[ip] = replace(cur, machine=cur.machine.release())` with `session.release()` or equivalent via the session API.
  - The "already disconnected" branch: simulate by calling `await session._close()` directly, then assert the rollback logs the "already disconnected" warning and re-raises. Pin this as a regression sentinel.
- [x] 7.6 `tests/unit/test_ssh_gateway_write_remote_file.py`:
  - `_write_remote_file` import path unchanged (still `infra/ssh/operations/deployment`). Verify no other change needed.
- [x] 7.7 `tests/integration/test_ssh_gateway.py`:
  - Fixture and call-site updates for `repository.list_free(None)` returning sessions; `machine.occupy()` / `repository.update_machine(busy)` patterns become `session.occupy()` or work directly on the session.
- [x] 7.8 `tests/e2e/test_full_cycle.py`:
  - `engines_dir = repository.get_engines_dir(...)` already removed by `cleanup-unused-repository-symbols` (reads from config). Verify.
  - `orchestrator._repository.get_machine_state(node_ip)` → `orchestrator._repository.get_session(node_ip).machine`.
- [x] 7.9 `tests/e2e/test_consume_retry.py`:
  - `check_repo.get_path(ssh_container["host"])` → `check_repo.get_session(ssh_container["host"]).path`.
- [x] 7.10 Run `uv run pytest -m unit` — all unit tests pass.
- [x] 7.11 Run `uv run pytest -m integration` — all integration tests pass (requires testcontainers).
- [x] 7.12 Run `uv run pytest -m e2e` — all e2e tests pass (requires testcontainers).

## 8. Re-exports and package surface

- [x] 8.1 `yascheduler/infra/ssh/__init__.py`: add `from .session import SSHMachineSession` to imports; add `SSHMachineSession` to `__all__`.
- [x] 8.2 `yascheduler/infra/ssh/operations/__init__.py`: keep `SSHMachineOperations` re-export. Remove any re-exports of narrow local Protocols (deleted).
- [x] 8.3 `yascheduler/domain/__init__.py`: ensure `MachineSession` is re-exported alongside `MachineRepository` and `MachineOperations`.

## 9. GRACE-lite knowledge graph

- [x] 9.1 Add `M-SSH-SESSION` module element to `docs/knowledge-graph.xml` with `<purpose>`, `<path>yascheduler/infra/ssh/session.py</path>`, `<depends>M-PLATFORM, M-SSH-EXCEPTIONS, M-DOMAIN</depends>` (NOTE: `my_backoff_exc` is moved TO `session.py` from `operations/base.py`; the dependency is on `M-PLATFORM` for `make_run_fn`/adapters, `M-SSH-EXCEPTIONS` for `SSHRetryExc`, and `M-DOMAIN` for `ConnectedMachine` — NOT on `M-SSH-OPERATIONS-BASE`), and `<annotations>` for `class-SSHMachineSession`, `fn-install_monitor`, `fn-cancel_monitor`, `fn-_close`, `fn-occupy`, `fn-release`, `fn-update`, `fn-run`, `fn-run_full`, `fn-run_bg`, `fn-upload`, `fn-open_sftp`, `fn-get_cpu_cores`, `fn-setup_node`, `fn-pgrep`, `fn-list_processes`, `type-MachineSession`.
- [x] 9.2 Update `M-SSH-REPOSITORY`:
  - `<purpose>` becomes "Connected-machine collection — registration, lifecycle, queries."
  - `<annotations>` loses `fn-_get_machine_state`, `fn-get_machine_state`, `fn-occupy`, `fn-release`, `fn-update_machine`, `fn-get_path`, `fn-get_quote`, `fn-get_hostname`, `fn-install_monitor`, `fn-cancel_monitor`, `fn-register_machine`, `fn-keys`, `fn-items`, `type-_MachineState`. Keeps `fn-connect`, `fn-disconnect`, `fn-disconnect_all`, `fn-list_free`, `fn-list_connected`, `fn-get_session`, `fn-contains`, `fn-__contains__`, `fn-__len__`, `class-SSHMachineRepository`.
  - `<depends>` loses references to monitor/task mechanics.
- [x] 9.3 Update `M-SSH-OPERATIONS` and `M-SSH-OPERATIONS-BASE`:
  - `M-SSH-OPERATIONS-BASE` annotation list shrinks (loses `fn-run`, `fn-run_full`, `fn-run_bg`, `fn-upload`, `fn-get_sftp`, `fn-pgrep`, `fn-list_processes`, `fn-get_cpu_cores`, `fn-setup_node`, `type-CommandExecutor`, `type-SftpProvider`, `type-StateAccessors`, `fn-my_backoff_exc`). These move to `M-SSH-SESSION`.
  - `M-SSH-OPERATIONS` keeps the facade composition annotations.
- [x] 9.4 Update `CrossLink`s:
  - Add `<CrossLink from="M-SSH-REPOSITORY" to="M-SSH-SESSION" relation="owns collection of" />`
  - Add `<CrossLink from="M-SSH-OPERATIONS" to="M-SSH-SESSION" relation="operates on" />`
  - Add `<CrossLink from="M-SSH-OPS-DEPLOY" to="M-SSH-SESSION" relation="takes session per call" />`
  - Add `<CrossLink from="M-SSH-OPS-DOWNLOAD" to="M-SSH-SESSION" relation="takes session per call" />`
  - Add `<CrossLink from="M-SSH-OPS-OCCUPANCY" to="M-SSH-SESSION" relation="installs monitor on" />`
  - Remove or update `CrossLink`s that referenced `_get_machine_state`, `_machines`, `_monitors`.
- [x] 9.5 Run `python3 scripts/grace_check.py` — must exit 0.
- [x] 9.6 Run `python3 scripts/grace_check.py --json` — confirm no errors.

## 10. Static checks and final validation

- [x] 10.1 `uv run zuban check` — passes.
- [x] 10.2 `uv run ruff check .` — passes.
- [x] 10.3 `uv run ruff format --check .` — passes.
- [x] 10.4 `uv run lint-imports` — passes (no circular imports; verify `session.py` and `repository.py` don't form a cycle).
- [x] 10.5 `openspec validate session-based-machine-handle --json` — passes.
- [x] 10.6 `openspec validate --all --json` — passes (all changes, including this one and `cleanup-unused-repository-symbols` if not yet archived).
- [x] 10.7 Confirm no `# noqa: SLF001` remains on `_get_machine_state` anywhere (the symbol is gone).
- [x] 10.8 Grep `yascheduler/` and `tests/` for stale references: `_get_machine_state`, `get_machine_state`, `_machines[`, `_monitors[`, `register_machine`, `_MachineState`, `MachineGateway` — confirm zero matches in production code (test references must have been rewritten per section 7).
