## 1. Domain model — `Node.ncpus` / `NewNode.ncpus` become `int | None`

> **Atomicity note:** Tasks 1.1 + 2.1 are interlocking — `NewNode.ncpus` default changes from `int = 0` to `int | None = None`, and `postgres.py:513`'s `or 0` coalescence is the other face of the same sentinel. Land 1.1 + 2.1 together (the `_row_to_node` change) so NULL round-trips as None rather than being silently coerced back to `0` (which the new CHECK forbids).
>
> **Merge-order note (per design "Ordering"):** this change applies last, after both `node-owns-connection-identity` and `connected-machine-runtime-only`. It assumes `ConnectedMachine.ncpus` is already removed and the `"CPUs count: %s"` log already lives in `SSHMachineRepository.connect`. Task 4.3 (cache priming) co-locates with that relocated log. If this change lands first by mistake, nothing breaks, but task 4.3's "co-locates with the relocated log" claim is stale until `connected-machine-runtime-only` lands.

- [x] 1.1 In `yascheduler/domain/model.py` `NewNode` (line 433): change `ncpus: int = 0` → `ncpus: int | None = None`. Update the field-semantics comment to state `None` = "no operator limit, discovered at spawn via the session cache".
- [x] 1.2 In `yascheduler/domain/model.py` `Node` (line 455): change `ncpus: int` → `ncpus: int | None`. Add a docstring paragraph stating the operator-set-config semantics (`None` = discover at spawn; `N > 0` = static) and that the magic `0` is removed.
- [x] 1.3 Update the `START_CONTRACT: Node` INPUTS line (line 440) to read `ncpus: int | None`; update the `START_CONTRACT: NewNode` (if present) and the `START_MODULE_MAP` / `CHANGE_SUMMARY` in `model.py` to reflect the type/default change.
- [x] 1.4 Update `yascheduler/domain/__init__.py` module map entry for `NewNode` / `Node` to note the `ncpus: int | None` field.

## 2. Persistence adapter — `None` round-trips through the DB

- [x] 2.1 In `yascheduler/infra/persistence/postgres.py` `_row_to_node` (line 513): change `ncpus=row.get("ncpus") or 0` → `ncpus=row.get("ncpus")`. SQL `NULL` now round-trips as Python `None` instead of being coerced to `0`. (This is the adapter face of the sentinel removal — atomic with 1.1.)
- [x] 2.2 Verify the write paths (`insert` at `postgres.py:350,366` and `update` at `postgres.py:431`) need no edit — they bind `new_node.ncpus` / `node.ncpus` directly, and the column is already `SMALLINT DEFAULT NULL` so binding `None` produces SQL `NULL`. Add a one-line code comment at each site noting `None` is the valid "no operator limit" value (not a sentinel to coalesce).
- [x] 2.3 Update `tests/unit/test_persistence_node_adapter.py`: change the "get handles null/zero ncpus" test (around line 114-135) to assert `node.ncpus is None` (not `== 0`) for a NULL row; rename the test to "get handles null ncpus"; add a symmetric test that a positive int row round-trips unchanged; add a test that `insert(NewNode(ncpus=None))` produces a row whose `get_by_id` returns `ncpus is None`.
- [x] 2.4 Update `START_CONTRACT: _row_to_node` INPUTS line and `CHANGE_SUMMARY` in `postgres.py` to drop the `or 0` coalescence mention.

## 3. DB schema + migration — `node_ncpus_positive` CHECK + backfill `0 → NULL`

- [x] 3.1 In `yascheduler/infra/persistence/sql/schema.sql` `CREATE TABLE yascheduler_nodes` (line 42): the `ncpus SMALLINT DEFAULT NULL` declaration stays; add a table-level `CONSTRAINT node_ncpus_positive CHECK (ncpus IS NULL OR ncpus > 0)` alongside the existing `node_port_range` / `node_jump_port_range` constraints (line 45-46 area).
- [x] 3.2 Create `yascheduler/infra/persistence/sql/migrations/013_ncpus_nullable.sql` with two statements IN THIS ORDER: (a) `UPDATE yascheduler_nodes SET ncpus = NULL WHERE ncpus = 0` (backfill FIRST — PostgreSQL validates existing rows when adding a CHECK constraint, so any pre-migration `0` row would fail the ALTER if it ran first); (b) `ALTER TABLE yascheduler_nodes ADD CONSTRAINT node_ncpus_positive CHECK (ncpus IS NULL OR ncpus > 0)`. Mirror migration 012's header comment style. Existing `NULL` and `> 0` rows are NOT touched by the backfill.
- [x] 3.3 Bump the `LATEST_MIGRATION` constant from `'012'` to `'013'` in the migrations module (locate via `grep -rn "LATEST_MIGRATION" yascheduler/infra/persistence/`).
- [x] 3.4 Add/extend the migration test (locate via the existing migration-012 test in `tests/`): assert migration `013` installs the `node_ncpus_positive` CHECK and backfills a `{ncpus=0}` row to `NULL` while leaving `{ncpus=8}` and `{ncpus=NULL}` rows untouched; assert `"013"` is recorded in `yascheduler_migrations`. Assert a post-migration `INSERT ... ncpus=0` raises a CHECK violation.
- [x] 3.5 Add/extend the schema-apply test: assert a fresh-database bootstrap (seeded to latest) has the `node_ncpus_positive` CHECK on `yascheduler_nodes`.

## 4. SSH session — `get_cpu_cores()` memoizes per session

- [x] 4.1 In `yascheduler/infra/ssh/session.py` `SSHMachineSession.__init__`: add a private `_cached_ncpus: int | None = None` instance field (the `None` here is the "not yet discovered" cache sentinel — distinct from any valid CPU count which is `>= 1`).
- [x] 4.2 Rewrite `SSHMachineSession.get_cpu_cores()` (line 230-232) to check `_cached_ncpus` first; on a miss, call the adapter via `make_run_fn(self._conn, self._adapter)` (preserving the existing `@my_backoff_exc()` retry on the miss path), store the result in `_cached_ncpus`, and return it. On a hit, return the cached value without invoking the adapter.
- [x] 4.3 In `yascheduler/infra/ssh/repository.py` `_connect_impl` `START_BLOCK_CREATE_MACHINE` (line 244-249): after `adapter.get_cpu_cores(...)` reads `ncpus` and constructs the `SSHMachineSession`, prime the session cache so the relocated `"CPUs count: %s"` log line (per `connected-machine-runtime-only`) and the cache fill happen in one step. The exact priming seam (a constructor kwarg, a post-construction setter, or a one-shot `get_cpu_cores()` call on the fresh session) is the implementer's choice — the observable contract is: the first user-facing `session.get_cpu_cores()` call returns the primed value with no adapter invocation.
- [x] 4.4 Update `START_CONTRACT: SSHMachineSession.get_cpu_cores` (if present) or add one: PURPOSE "Return CPU core count, memoized per session (cache miss invokes adapter with retry; cache hit returns without adapter invocation)"; update the `Retry and backoff policy` contract wording in `repository.py` / `session.py` if it claims every call retries.
- [x] 4.5 Update `START_MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` in `session.py` and `repository.py`.

## 5. Orchestrator — explicit `None`-check ncpus resolution

- [x] 5.1 In `yascheduler/application/orchestrator.py` `_start_task_on_machine` `START_BLOCK_RESOLVE_NCPUS` (line 183-191): replace the falsy short-circuit `ncpus = (node and node.ncpus) or await session.get_cpu_cores()` with the explicit form `ncpus = node.ncpus if node is not None and node.ncpus is not None else await session.get_cpu_cores()`.
- [x] 5.2 Update the `START_CONTRACT: Orchestrator._start_task_on_machine` SIDE_EFFECTS line (line 174) to read "falls back to `session.get_cpu_cores()` when the node is absent OR `node.ncpus is None`".
- [x] 5.3 Add/extend orchestrator unit tests (`tests/unit/test_application_orchestrator.py`): (a) when the allocated `Node.ncpus == 8`, `session.get_cpu_cores()` is NOT called and `8` flows to `task_deployer.start_task_on_machine`; (b) when the allocated `Node.ncpus is None`, `session.get_cpu_cores()` IS called and its return value flows to the deployer; (c) when the node is absent (`get_by_id` returns `None`), `session.get_cpu_cores()` is called.
- [x] 5.4 Update `CHANGE_SUMMARY` in `orchestrator.py`.

## 6. Cloud allocator — remove write-back + vestigial discovery

- [x] 6.1 In `yascheduler/infra/cloud/manager.py` `_setup_vm` (line 412): change `return replace(node, enabled=True, ncpus=ncpus)` → `return replace(node, enabled=True)`. The frozen-dataclass `replace` preserves `node.node_id`, `hostname`, `jump_*`, etc.
- [x] 6.2 In `_setup_vm`: remove the `START_BLOCK_GET_CPUS` block (line 397-404) — the standalone `ncpus = await session.get_cpu_cores()` call and its `CloudSetupError` wrapper. Discovery now happens once in `_connect_to_vm`'s `repository.connect` call and primes the session cache (slice 4). Update the surrounding log/debug lines that referenced the local `ncpus` variable.
- [x] 6.3 In `allocate`'s DONE log (line 229-235): change the `ncpus=%d` format specifier to `ncpus=%s` (renders `None` as `"None"` rather than raising `TypeError`). Keep the field in the log so it is visible for future static-config cloud nodes.
- [x] 6.4 Update `START_CONTRACT: CloudProvisionerImpl._setup_vm` and the `allocate` contract INPUTS/SIDE_EFFECTS to drop the `ncpus` write-back mention; update `MODULE_MAP` / `CHANGE_SUMMARY` in `manager.py`.
- [x] 6.5 Add/extend cloud-provisioner unit tests (`tests/unit/test_cloud_provisioner_impl.py`): assert the returned `Node.ncpus is None` after `allocate`/`_setup_vm`; assert the standalone `get_cpu_cores()` is NOT called inside `_setup_vm` (the session's `connect`-time discovery is the only call); assert the DONE log formats `None` without raising.

## 7. CLI — encode `None` / display `None`

- [x] 7.1 In `yascheduler/entrypoints/cli/manage_node.py` `_add_node` `START_BLOCK_INSERT_TMP` (line 293-309): change `ncpus=(spec.ncpus if spec.ncpus is not None else 0)` → `ncpus=spec.ncpus`. `HostSpec.ncpus` is already `int | None`; an absent `~ncpus` clause now produces `NewNode(ncpus=None)` directly.
- [x] 7.2 In `yascheduler/entrypoints/cli/show_nodes.py` table renderer (line 216): change `"MAX" if row.ncpus == 0 else str(row.ncpus)` → `"MAX" if row.ncpus is None or row.ncpus == 0 else str(row.ncpus)`. The `== 0` branch is defensive against pre-migration rows viewed before migration 013 runs; post-migration only `None` occurs.
- [x] 7.3 In `show_nodes.py` `_NodeView` dataclass (line 153) and the `--json` output (line 252): the `ncpus` field widens to `int | None` with `Node`'s; verify the `--json` encoder emits `null` for `None` (Python `json.dumps(None)` → `"null"` — no code change beyond the type flowing through). Update the `--json` schema docstring/comment to read `int | null`.
- [x] 7.4 Update CLI unit tests (`tests/unit/test_cli_manage_node.py`, `tests/unit/test_cli_show_nodes.py`): (a) the "node default ncpus zero when absent" test (around line 436-447) becomes "node default ncpus None when absent" and asserts `added_node.ncpus is None`; (b) add a `yanodes` table test asserting the NCPUS cell is `MAX` for `ncpus=None`; (c) add a `yanodes --json` test asserting `"ncpus": null` for a `None` node.
- [x] 7.5 Update `START_MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` in `manage_node.py` and `show_nodes.py`.

## 8. Test-fixture sweep + GRACE-lite / knowledge-graph consistency

> **Outcome:** all existing tests pass under the widened `int | None` type, the GRACE-lite graph and contracts reflect the new shape, and the change is ready for review.

- [x] 8.1 Sweep `tests/` for `Node(..., ncpus=0)` and `NewNode(..., ncpus=0)` constructor sites (grep: `rg -n "ncpus=0" tests/`). Each becomes `ncpus=None` (the semantically-correct "no operator limit" value) UNLESS the test specifically exercises a legacy-`0` display path (in which case keep `0` and assert the `MAX`/null behavior). Positive-int fixtures (`ncpus=2`, `ncpus=4`, `ncpus=8`) stay unchanged — the type only widens.
- [x] 8.2 Sweep `tests/` for assertions that read `node.ncpus == 0` or `node.ncpus is 0` (grep: `rg -n "ncpus == 0|ncpus is 0" tests/`); flip each to `node.ncpus is None` where it follows from a `None`/NULL source.
- [x] 8.3 Run the full verification suite per `AGENTS.md`: `uv run pytest -m unit`, `uv run pytest -m integration`, `uv run pytest -m e2e` (integration/e2e use testcontainers — verify the migration applies cleanly against a fresh Postgres and that the backfill `0→NULL` behaves on a seeded DB); `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`; `openspec validate --all --json`; `python3 scripts/grace_check.py`.
- [x] 8.4 Update `docs/knowledge-graph.xml`: the `M-DOMAIN-MODEL` module's `<annotations>` for `Node` / `NewNode` gain a note that `ncpus` is now `int | None` (operator-set config); add or update the `CrossLink` from `M-SSH-SESSION` to `M-DOMAIN-MODEL` noting the session cache primes `Node.ncpus` discovery. Private-to-Node changes — verify whether the graph's `M-DOMAIN-MODEL` annotation text mentions the old `int`/`0` shape and update only if so.
- [x] 8.5 Final review pass: confirm no remaining `ncpus = ... or 0` coalescence, no remaining `%d` format on `node.ncpus`, no remaining falsy short-circuit `(node and node.ncpus) or ...` in production code. The magic `0` is gone from every layer (domain, persistence, orchestrator, cloud, CLI).
