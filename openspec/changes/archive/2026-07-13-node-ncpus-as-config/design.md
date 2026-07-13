## Context

`Node.ncpus` is typed `int` with a magic `0` sentinel meaning "unknown / discover at spawn". The field is written inconsistently across the two node-add paths:

- **Cloud** (`CloudProvisionerImpl._setup_vm`, `manager.py:412`): persists a runtime-discovered value into `Node.ncpus` once via `replace(node, enabled=True, ncpus=ncpus)`. The discovery happens at a *second* site (`_setup_vm` line 399) on top of the discovery already performed in `SSHMachineRepository.connect` (`repository.py:245`). Cloud treats the field as a discovery cache.
- **Static** (`yasetnode` / `_add_node`, `manage_node.py:337`): only flips `enabled=True`; never persists the discovered `ncpus`. `Node.ncpus` stays `0` forever. Static treats the field as "always re-discover".

The consumer — `Orchestrator._start_task_on_machine` (`orchestrator.py:190`) — papers over both with a falsy short-circuit:

```python
ncpus = (node and node.ncpus) or await session.get_cpu_cores()
```

`SSHMachineSession.get_cpu_cores()` (`session.py:230-232`) is **not cached** — every call performs a real SSH exec (`getconf _NPROCESSORS_ONLN` on Linux, PowerShell `$env:NUMBER_OF_PROCESSORS` on Windows). So a static session that deploys N tasks makes N redundant remote CPU-count round-trips.

Two in-flight OpenSpec changes defer this concern explicitly:

- `connected-machine-runtime-only/design.md:48` — "Node.ncpus persistence asymmetry for static nodes ... NOT addressed here. Separate concern; tracked as a potential follow-up."
- `node-owns-connection-identity/design.md:27` — "Static-Node ncpus persistence asymmetry — separate proposal."

This change is that follow-up. It applies **last**, assuming the post-state of both pending changes: `ConnectedMachine.ncpus` already removed, the misplaced `"CPUs count: %s"` log already relocated to `SSHMachineRepository.connect` (the single discovery site, `repository.py:245`).

Constraints from project standards (`AGENTS.md`): DB schema changes MUST include migrations; public INI config format and CLI command surface are stable (no CLI command/flag changes here — only internal encoding); `python >= 3.9`; no new dependencies.

## Goals / Non-Goals

**Goals:**

- Reinterpret `Node.ncpus` as **operator-set static config** (`int | None`): `None` = "no operator limit, discover at spawn"; `N > 0` = "explicit static value, use directly". Eliminate the magic `0` sentinel.
- Remove the cloud write-back so both add paths share one semantics: `Node.ncpus` is config, not a discovery cache.
- Memoize `SSHMachineSession.get_cpu_cores()` per session lifetime so the now-load-bearing per-spawn discovery costs at most one remote exec per connection (primed by `SSHMachineRepository.connect`'s existing discovery).
- Make the orchestrator's resolution explicit and honest about the `int | None` type.
- Add a DB CHECK constraint `(ncpus IS NULL OR ncpus > 0)` and backfill existing `0` rows to `NULL`.

**Non-Goals:**

- `Node.jump_*` fields — owned by `node-owns-connection-identity`.
- `ConnectedMachine.ncpus` removal and the `"CPUs count: %s"` log relocation — owned by `connected-machine-runtime-only`.
- A `cloud.ncpus` config option letting operators pre-set cloud node CPU counts. Future extension; this change only *enables* it by making the field config-shaped, it does not add the config key.
- Caching discovery across sessions (cross-connection cache). Out of scope — per-session is sufficient and avoids invalidation complexity.
- Changing the `get_cpu_cores()` SSH command or platform adapters. They stay as-is; only the session wrapper memoizes.

## Decisions

### D1: `Node.ncpus` and `NewNode.ncpus` become `int | None`

`NewNode.ncpus` default changes `int = 0` → `int | None = None`. `Node.ncpus` widens `int` → `int | None` (no default — `Node` is always constructed from a DB row). The `Node` contract `INPUTS` line updates to `ncpus: int | None`.

Semantics: `None` = "no operator limit, the orchestrator discovers at spawn via the session cache". `N > 0` = "operator-set static config, used directly, no discovery". The magic `0` is gone — `0` is no longer a valid stored value (enforced by the DB CHECK in D6 and by the adapter in D4).

**Alternative considered:** keep `int` and document `0` as the sentinel explicitly. Rejected: the sentinel is already leaking into CLI display (`show_nodes.py:216` maps `0 → "MAX"`), into the orchestrator's falsy short-circuit, and into test fixtures. A nullable type makes the "unset" state honest and removes the implicit `0`-is-special coupling between every reader and writer.

### D2: Remove the cloud write-back; drop the vestigial `_setup_vm` discovery

`CloudProvisionerImpl._setup_vm` (`manager.py:412`) currently ends with `return replace(node, enabled=True, ncpus=ncpus)`. After D1 the final replace becomes `return replace(node, enabled=True)` — `ncpus` is no longer stamped onto the `Node`.

The standalone `get_cpu_cores()` call inside `_setup_vm` (`manager.py:399`, site b) becomes vestigial: its only purpose was to feed the write-back. It is removed. Discovery now happens exactly once, in `SSHMachineRepository.connect` (`repository.py:245`, site a), inside `_connect_to_vm`'s call to `repository.connect`. That discovery primes the session cache (D3), so the cloud node's first spawn reads the cached value instead of re-executing remotely.

The `allocate` DONE log at `manager.py:230` currently formats `node.ncpus` with `%d`. After D1 a cloud `Node.ncpus` is `None` until/unless a future cloud config supplies a static value, so `%d` would raise `TypeError`. The log switches to `ncpus=%s` (renders `None` as `"None"`) or drops the field from the DONE line. Chosen: switch to `%s` — the field stays visible for the future static-config case and for any node that carries an explicit value.

**Alternative considered:** keep the write-back for cloud only, treating cloud and static with different semantics. Rejected: that is the current asymmetric state, which is exactly what this change removes. One semantics for both add paths is the point.

### D3: `SSHMachineSession.get_cpu_cores()` memoizes per session

`SSHMachineSession` gains a private `_cached_ncpus: int | None = None` field (sentinel meaning "not yet discovered", distinct from any valid CPU count which is `>= 1`). `get_cpu_cores()` checks the field first; on a miss it calls the adapter, stores the result, returns it. Subsequent calls in the same session return the cached value with no SSH exec.

CPU count is invariant for the lifetime of one SSH connection: a cloud VM resize reboots the VM (connection drops, session discarded, cache resets on reconnect); hot-add CPU on bare metal is a pathological case outside the scheduler's operational model, and an operator who needs it can set `ncpus` explicitly.

The discovery already performed in `SSHMachineRepository.connect` (`repository.py:245`) primes this cache: after `connect` constructs the `SSHMachineSession`, it calls `session.get_cpu_cores()` once (or exposes a priming seam) so the relocated `"CPUs count: %s"` log line (per `connected-machine-runtime-only`) and the cache fill happen in one step. This makes the session cache and the log relocation complementary rather than conflicting.

**Alternatives considered:**

- *`@cache` / `@lru_cache` on the async method.* Rejected: stdlib `lru_cache` on `async def` caches the coroutine object, not the result; re-awaiting raises `RuntimeError: cannot reuse already awaited coroutine`. There is no stdlib async memo, and adding a dependency (`async-lru`, `cachetools`) for a single call site violates the no-new-deps rule.
- *No cache — accept per-spawn SSH exec as the design.* Rejected: this is the current behavior being fixed. With the write-back removed (D2), cloud nodes would also pay per-spawn. The session cache is the fix.

### D4: Persistence adapter passes `None` through

`PostgresNodeRepository._row_to_node` (`postgres.py:513`) currently coalesces `ncpus=row.get("ncpus") or 0`. This `or 0` is the other face of the magic sentinel — it converts SQL `NULL` back to `0`. It changes to `ncpus=row.get("ncpus")` so `NULL` round-trips as `None`.

The write paths (`insert` at `postgres.py:350,366`, `update` at `postgres.py:431`) bind `new_node.ncpus` / `node.ncpus` directly. The DB column is already `SMALLINT DEFAULT NULL` (`schema.sql:42`), so binding `None` works without SQL changes. The `insert.sql` / `update.sql` parameterized statements need no edit — `:ncpus` accepts NULL.

### D5: Orchestrator resolution becomes an explicit `None`-check

`_start_task_on_machine` (`orchestrator.py:190`) switches from the falsy short-circuit to an explicit form:

```python
ncpus = (
    node.ncpus
    if node is not None and node.ncpus is not None
    else await session.get_cpu_cores()
)
```

Functionally equivalent for `int | None` (the only falsy `int` in the valid set would be `0`, which D1/D6 make unstoreable), but honest about the type and robust against any future re-introduction of `0` as a value. The contract's `SIDE_EFFECTS` line updates: "falls back to `session.get_cpu_cores()` when the node is absent or `node.ncpus` is `None`".

### D6: DB migration `013_ncpus_nullable.sql` — CHECK + backfill `0 → NULL`

The column is already `SMALLINT DEFAULT NULL`; no type change. The migration does two things:

1. `UPDATE yascheduler_nodes SET ncpus = NULL WHERE ncpus = 0;` — backfill the magic-sentinel rows to the honest `None` representation.
2. Install `CHECK (ncpus IS NULL OR ncpus > 0)` on `yascheduler_nodes`.

The backfill runs FIRST because PostgreSQL's `ALTER TABLE ... ADD CONSTRAINT
... CHECK` validates all existing rows against the new constraint by default.
Running ADD CONSTRAINT first would fail on any pre-migration row with `ncpus =
0` (the legacy sentinel). Backfilling those rows to `NULL` first makes the
constraint application safe on databases with existing zero-valued rows.

Existing `NULL` rows (already semantically "unknown") and `> 0` rows (operator-set or previously cloud-cached) are **untouched**. Per the user's decision, the previously cloud-cached discovered values (e.g. `8`) are left as-is: they are valid positive ints and the CHECK permits them. They will be interpreted as "operator-set static config" going forward — which is the correct conservative reading (a cached `8` behaves identically to a configured `8`: used directly, no per-spawn discovery). New cloud nodes created after this change get `None` and discover per-spawn via the session cache.

**Alternative considered (strict reset):** `UPDATE ... SET ncpus = NULL WHERE cloud IS NOT NULL` to force all existing cloud nodes back onto the discovery path. Rejected by the user: only `0` is migrated; `> 0` rows, regardless of origin, stay. Rationale: a previously-discovered `8` is a correct upper bound and re-discovering it per-spawn buys nothing once the session cache (D3) makes discovery cheap.

### D7: CLI encoding and display

`yasetnode` (`manage_node.py:304`) currently encodes an absent `~ncpus` as `0`: `ncpus=(spec.ncpus if spec.ncpus is not None else 0)`. It changes to `ncpus=spec.ncpus` — `HostSpec.ncpus` is already `int | None` (`None` when `~N` is absent), so this passes `None` straight through to `NewNode`. The `HostSpec` dataclass and `_parse_host_spec` are unchanged.

`yanodes` (`show_nodes.py:216`) currently maps `row.ncpus == 0 → "MAX"`. It generalizes to `row.ncpus is None or row.ncpus == 0 → "MAX"` (the `== 0` half is defensive against pre-migration rows viewed before the migration runs; post-migration only `None` occurs). The `_NodeView` dataclass (`show_nodes.py:153`) passes `node.ncpus` through unchanged — its `ncpus` field widens to `int | None` with `Node`'s.

### Ordering

This change applies **last**, after both `node-owns-connection-identity` and `connected-machine-runtime-only`. It assumes their post-state:

- `ConnectedMachine.ncpus` is already gone — D3's session cache replaces the role its `ncpus` field played (the misplaced log reader).
- The `"CPUs count: %s"` log already lives in `SSHMachineRepository.connect` — D3's priming step co-locates the cache fill with that log.
- `Node.jump_*` already exists — D2's `replace(node, enabled=True)` preserves them (frozen dataclass `replace` keeps all other fields).

If this change lands first by mistake, none of D1-D7 break — but D3's "priming co-locates with the relocated log" claim becomes stale until `connected-machine-runtime-only` lands. Tasks should call out the ordering preference without enforcing it at the code level.

## Risks / Trade-offs

**[Risk] Cloud nodes now discover per-spawn until a future cloud config supplies `ncpus`** → With D3's session cache the cost is one `getconf` exec per cloud-session lifetime (the session is created in `_connect_to_vm` and reused across the VM's tasks). Cloud VMs are ephemeral and handle a bounded task count, so the per-session cost is negligible. Mitigation is D3 itself; the future `cloud.ncpus` config option (out of scope) eliminates even that.

**[Risk] `manager.py:230` `%d` format raises `TypeError` on `None` if missed** → D2 explicitly switches this to `%s`. The tasks phase must touch this line; a test that exercises `allocate` with `node.ncpus is None` guards against regression.

**[Risk] `_row_to_node`'s `or 0` coalescence missed during D4** → The adapter would silently convert `NULL` back to `0`, re-introducing the sentinel the CHECK (D6) forbids — the next insert/update of that row would violate the CHECK. Mitigation: the existing `test_persistence_node_adapter.py:114-135` "get handles null/zero ncpus" test is updated to assert `ncpus is None` (not `== 0`) for a NULL row, making the adapter behavior explicit.

**[Risk] Hot-add CPU on a live bare-metal session goes unobserved** → CPU count is cached for the session's lifetime. An operator who hot-adds CPUs and wants the scheduler to see them without reconnecting must set `ncpus` explicitly via `yasetnode ~N`. Accepted: hot-add during a live scheduler session is outside the operational model; reconnect (cache reset) covers the reboot-based resize case.

**[Risk] Migration backfill `0 → NULL` is one-directional** → A deployment that rolls back to a pre-D6 binary after the migration has run will see `NULL` rows where it expected `0`. The pre-D6 `_row_to_node` `or 0` coalescence converts them back to `0`, so the old binary keeps working (the sentinel round-trips). The CHECK constraint added by the migration is forward-compatible with the old binary (it only forbids `0` and negatives, which the old binary never writes). Rollback is therefore safe; the migration does not need a down-script.

**[Trade-off] Previously cloud-cached `> 0` rows become "static config" semantically** → A cloud node row with `ncpus=8` created before this change will, after migration, be treated as operator-set static config (used directly, no per-spawn discovery) rather than as a stale cache entry. This is intentional (D6): the value is correct and re-discovering it buys nothing with D3 in place. If the VM's actual CPU count later diverges (e.g. provider changes the instance shape under the same `external_id`), the stale `8` would misallocate. Accepted: cloud VMs are identified by `external_id` and deleted on idle; long-lived shape changes under a reused `external_id` are not a supported operational pattern.
