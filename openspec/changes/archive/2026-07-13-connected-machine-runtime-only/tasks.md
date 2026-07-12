## 1. Domain model — slim `ConnectedMachine`

> **Atomicity note:** Tasks 1.1 + 3.2 are interlocking — `ConnectedMachine` fields are required (no defaults), so dropping them in 1.1 without updating the construction site in 3.2 (or vice versa) raises `TypeError`. Land 1.1 + 3.2 in one commit. Similarly 1.2 + 2.1 must land together (`MachineBusyError.__init__` arity change vs. its sole call site).

> **Merge-order note (per design D6):** this change is independent of the sibling `node-owns-connection-identity` change — they touch disjoint surfaces and merge cleanly in either order. The one shared file is `SSHMachineRepository.connect` (repository.py); this change edits the `ConnectedMachine(...)` construction kwargs, the sibling edits the `_open_connection(...)` / `connect(...)` signatures — different parts of the same method.

- [x] 1.1 In `yascheduler/domain/model.py` `ConnectedMachine` (lines 470-521): drop fields `hostname: str` and `ncpus: int`. The frozen dataclass becomes `node_id: NodeId` (first), `platform: str`, `state: MachineState = MachineState.FREE`, `free_since: float | None = None`.
- [x] 1.2 In `ConnectedMachine.occupy()` (line 506): change `raise MachineBusyError(self.node_id, self.hostname)` → `raise MachineBusyError(self.node_id)`. (Atomic with task 2.1.)
- [x] 1.3 Update the `ConnectedMachine` docstring (lines 470-474) to drop the "with state and platform info" tail — the entity now carries only `node_id` + `platform` + runtime state.
- [x] 1.4 Update `START_MODULE_CONTRACT` / `START_CONTRACT: ConnectedMachine.occupy` / `START_BLOCK_VALIDATE_FREE` annotations in `model.py` to drop `hostname` / `ncpus` mentions.
- [x] 1.5 Update `LAST_CHANGE` / `CHANGE_SUMMARY` in `model.py`.

## 2. Domain exception — slim `MachineBusyError`

- [x] 2.1 In `yascheduler/domain/exceptions.py` `MachineBusyError` (lines 86-92): change `__init__(self, node_id: NodeId, hostname: str)` → `__init__(self, node_id: NodeId)`; drop the `self.hostname = hostname` line; change message format to `f"machine ({node_id}) is busy"` (drop the `"at {hostname}"` segment).
- [x] 2.2 Leave `MachineConnectionError` (lines 95-104) UNCHANGED — its `hostname` comes from `node.hostname` at the raise site in `SSHMachineRepository.connect`, not from `ConnectedMachine`.
- [x] 2.3 Update `START_MODULE_CONTRACT` / module map / `CHANGE_SUMMARY` in `exceptions.py`: drop "MachineBusyError/MachineConnectionError gain node_id first arg, hostname replaces ip" stale references where they describe `MachineBusyError` (the `MachineConnectionError` line stays accurate).
- [x] 2.4 Update `yascheduler/domain/__init__.py` module map (line 40): change "MachineBusyError - Operation attempted on a busy machine (carries node_id, hostname)" → "(carries node_id)". Leave the `MachineConnectionError` line as-is.

## 3. SSH repository — move log, slim construction

- [x] 3.1 In `yascheduler/infra/ssh/repository.py` `_connect_impl` (around line 230, inside `START_BLOCK_CREATE_MACHINE`): after `ncpus = await adapter.get_cpu_cores(make_run_fn(conn, adapter))`, add `self._log.info("[SSHRepository][connect][CPUS] hostname=%s ncpus=%d", node.hostname, ncpus)`. Keep the existing debug log line if any.
- [x] 3.2 In the same block, change the `ConnectedMachine(...)` construction to drop `hostname=node.hostname` and `ncpus=ncpus` kwargs. The construction becomes `ConnectedMachine(node_id=node.node_id, platform=adapter.platform, state=MachineState.FREE, free_since=time.monotonic())`.
- [x] 3.3 Leave the `SSHMachineSession(hostname=node.hostname, ...)` construction (line 243) UNCHANGED — `session._hostname` is the transport-echo used by ~11 operator-facing log lines; it stays sourced from `node.hostname`.
- [x] 3.4 Update `START_CONTRACT: SSHMachineRepository.connect` / `_connect_impl` INPUTS lists; update `START_BLOCK_CREATE_MACHINE` block markers; update `LAST_CHANGE` / `CHANGE_SUMMARY`.

## 4. SSH session — drop misplaced log

- [x] 4.1 In `yascheduler/infra/ssh/session.py` `SSHMachineSession.setup_node` (line 243): delete the `self._log.info("CPUs count: %s", self._machine.ncpus)` line. The method now begins directly with the `retry = my_backoff_exc(...)` / `await retry(self._adapter.setup_node)(...)` block.
- [x] 4.2 Update `START_CONTRACT: SSHMachineSession.setup_node` if its PURPOSE or INPUTS mention CPU count; update `LAST_CHANGE` / `CHANGE_SUMMARY`.

## 5. Unit tests — domain

- [x] 5.1 `tests/unit/test_domain_model.py`: update `ConnectedMachine` construction sites (drop `hostname=...`, `ncpus=...` kwargs); update the `occupy`/`release` tests to assert the slimmer shape; update the `TestNodeStatus` tests if they touch `ConnectedMachine` (they don't, but verify). Update the LAST_CHANGE note in the file.
- [x] 5.2 Add / update the `ConnectedMachine occupy on BUSY raises MachineBusyError with node_id only` test: construct a `ConnectedMachine(node_id=NodeId(7), platform="linux", state=MachineState.BUSY)`, call `occupy()`, assert `MachineBusyError` raised, `e.node_id == NodeId(7)`, and `not hasattr(e, "hostname")` (or `getattr(e, "hostname", None) is None`).
- [x] 5.3 `tests/unit/test_domain_exceptions.py`: update `MachineBusyError(NodeId(1), "10.0.0.1")` → `MachineBusyError(NodeId(1))`; drop assertions on `exc.hostname`; update message assertion to match `"machine (NodeId(value=1)) is busy"` (or whatever the project's `NodeId.__repr__` produces). Verify `MachineConnectionError` tests are NOT touched.
- [x] 5.4 In `test_domain_exceptions.py` line 448 area: the `MachineBusyError(NodeId(1), "0.0.0.0")` call (used in some hierarchy/exception-group test) → `MachineBusyError(NodeId(1))`.

## 6. Unit tests — SSH / application / services layers

> **Umbrella audit (run before per-file fixes):** `rg -n 'ConnectedMachine\(' tests/` and `rg -n 'MachineBusyError\(' tests/` — every match must be updated to the slimmer shape. The per-file list below is the known-affected set; the rg audit catches anything missed.

- [x] 6.1 `tests/unit/test_ssh_gateway.py`: update `ConnectedMachine` assertions (drop `.hostname` / `.ncpus` reads on `result[0].machine` at lines 408, 425, 483 — these now read only `.node_id`, `.platform`, `.state`, `.free_since`). Update any direct `ConnectedMachine(...)` constructions in test fixtures.
- [x] 6.2 Add / verify a test that the CPU-count log now emits from `SSHMachineRepository.connect` (the discovery site) and NOT from `SSHMachineSession.setup_node` — use `caplog` or the project's log-assertion convention.
- [x] 6.3 `tests/unit/test_cloud_provisioner_impl.py`: audit for `MachineBusyError(NodeId(...), "...")` constructions or `.hostname` attribute reads on the exception — update to single-arg form. Also audit for `ConnectedMachine(hostname=..., ncpus=...)` constructions (e.g. `machine.hostname = node.hostname if node is not None else "[IP]"` at line 142, `machine.hostname = kw.get("ip", "[IP]")` at line 395) — these are SimpleNamespace-style mocks of the `machine` attribute; if they mock `hostname`/`ncpus`, drop those fields.
- [x] 6.4 `tests/unit/test_application_events.py` and `tests/unit/test_application_use_cases.py`: drop `free_machine.hostname = "10.0.0.1"` style SimpleNamespace mock fields if nothing reads them; if tests read `.hostname`, replace with `session.hostname` (the session-level transport echo, which is unchanged).
- [x] 6.5 `tests/unit/test_application_orchestrator.py`: update the FIVE `ConnectedMachine(hostname=..., ncpus=...)` constructions at lines 782, 818, 888, 924, 962 — drop `hostname=` / `ncpus=` kwargs.
- [x] 6.6 `tests/unit/test_domain_services.py`: update the EIGHT `ConnectedMachine(hostname=..., ncpus=...)` constructions at lines 65, 82, 99, 106, 141, 144, 162, 169 — drop `hostname=` / `ncpus=` kwargs.
- [x] 6.7 `tests/unit/test_domain_ports.py:130`: update `_make_session_stub()`'s `ConnectedMachine(node_id=..., hostname="10.0.0.1", platform="linux", ncpus=1)` → drop `hostname=` / `ncpus=`.
- [x] 6.8 `tests/unit/test_cloud_alloc_session_lifecycle.py:83`: update `FakeMachineSession.__init__`'s `ConnectedMachine(hostname=hostname, platform=platform, ncpus=4, ...)` → drop `hostname=` / `ncpus=` kwargs.
- [x] 6.9 Re-run the umbrella `rg -n 'ConnectedMachine\(' tests/` after 6.1-6.8 and confirm zero remaining `hostname=` / `ncpus=` kwargs on the constructor.

## 7. Integration / e2e tests

- [x] 7.1 Audit `tests/integration/` and `tests/e2e/` for `ConnectedMachine(...)` constructions with `hostname=` / `ncpus=` kwargs — update to slimmer shape.
- [x] 7.2 Audit for `MachineBusyError(NodeId(...), "...")` constructions — update to single-arg form.
- [x] 7.3 If there is an SSH testcontainers test that hits `setup_node`, verify the CPU log is now emitted from `connect` (caplog assertion).

## 8. External-consumer audit

- [x] 8.1 Audit `yascheduler/entrypoints/aiida_plugin.py` (the AiiDA scheduler plugin — single file, NOT a directory) for any direct `ConnectedMachine(...)` construction or `MachineBusyError(...)` construction — verify neither is impacted.
- [x] 8.2 Audit `yascheduler/entrypoints/client.py` (the Python client surface) for `ConnectedMachine` references — verify no direct construction.
- [x] 8.3 If either audit finds a hit, document it in the proposal's Impact section (the BREAKING flag is already there) and add a migration note.

## 9. GRACE-lite knowledge graph and contracts

- [x] 9.1 Update `docs/knowledge-graph.xml` `M-DOMAIN-MODEL` annotations: `class-ConnectedMachine` PURPOSE drops "with state and platform info" tail. No `M-DOMAIN-EXCEPTIONS` annotation changes (the class name is unchanged; only the constructor shape changed, which is not graph-level).
- [x] 9.2 Update `M-SSH-REPOSITORY` / `M-SSH-SESSION` annotations only if the `class-ConnectedMachine` annotation lives there — check and update if so.
- [x] 9.3 Run `python3 scripts/grace_check.py` — exit 0 required.

## 10. Static checks and spec validation

- [x] 10.1 `uv run pytest -m unit` — all green
- [x] 10.2 `uv run pytest -m integration` — all green (or skipped if no testcontainers)
- [x] 10.3 `uv run zuban check` — clean
- [x] 10.4 `uv run ruff check .` — clean
- [x] 10.5 `uv run ruff format --check .` — clean
- [x] 10.6 `uv run lint-imports` — clean
- [x] 10.7 `openspec validate --all --json` — exit 0
- [x] 10.8 `python3 scripts/grace_check.py` — exit 0 (re-run after any final edits)
