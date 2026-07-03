## Context

The Task↔Node binding is the last ip-as-identity surface with a wide cascade. `yascheduler_tasks.ip` (exposed in the domain as `Task.allocated_ip`) is the schema column that records which Node a Task runs on. Migration 003 dropped the `UNIQUE` constraint on `yascheduler_nodes.ip`; duplicate IPs are now a supported configuration (same IP reachable via different jump hosts / ports / usernames — the original motivation for the renovation). The NodeRepository mutators and the deallocate flow have already been rekeyed to `NodeId`. The remaining read path that blocks the SSH `_sessions` rekey (Surface A) is `_task_consumer`'s `get_session(task.allocated_ip)` — it cannot switch to `allocated_node_id` until the column exists and is written.

The bind site is a single function: `_try_start_on_machine` calls `task.allocate_to(session.ip)`. `_find_free_machines` already loads `Node` objects (carrying `node_id`) from `list_enabled()` but discards them to a set of IPs, then returns bare `MachineSession` objects. The `Node` is in hand; it is thrown away.

Constraints:
- `client.py`'s response keeps the `ip` field (public API stability — `AGENTS.md`).
- The cloud-host argument to `clouds.deallocate(cloud, ip)` / `adapter.delete_node(host=ip)` stays ip-keyed forever (Surface C — the cloud SDK has no NodeId concept).
- The SSH `MachineSession` does not yet carry `node_id` (that is Surface A). Session↔Node matching must stay by ip in this change; full disambiguation for dup-IP nodes lands with A.
- `allocated_ip` stays on the schema, on `Task`/`NewTask`, and in logging — this change is additive.

## Goals / Non-Goals

**Goals:**
- Add `allocated_node_id` (nullable FK to `yascheduler_nodes(node_id)`, `ON DELETE SET NULL`) to `yascheduler_tasks` via migration 004, and backfill it for all existing tasks by joining on `ip` (assuming ip is unique-or-NULL at migration time).
- Add `allocated_node_id: NodeId | None` to `Task` and `NewTask`.
- Change `Task.allocate_to(ip: str)` to `Task.allocate_to(node: Node)`, binding both `allocated_ip` and `allocated_node_id` in one call.
- Carry the `Node` from `_find_free_machines` to `_try_start_on_machine` so the bind site has `node.node_id`. Return `list[(MachineSession, Node)]`.
- Write `allocated_node_id` through the 5 task SQL files (`insert`, `update_by_id`, `get_by_id`, `list_by_status`, `list_by_jobs`) and read it back in `_row_to_task`.
- Surface A's read-path switch is unblocked: the column exists and is populated for new allocations.

**Non-Goals:**
- Switch any read site to `allocated_node_id`. All 6 read sites (`_task_consumer get_session`, `busy_ips`, `busy_node_ips`, `abandon_node matching`, `show_nodes`, `check_status`) keep using `allocated_ip`. They switch in Surface A (`ssh-rekey-node-id`).
- Rekey `MachineRepository._sessions` to `NodeId` (Surface A).
- Add a `node_id` property to `MachineSession` (Surface A).
- Disambiguate session↔node matching for dup-IP nodes (Surface A — sessions will carry `node_id`).
- Rekey `NodeRepository.get(ip)` / `get_by_ips` (Surface D).
- Remove `allocated_ip` from the schema, the domain, `client.py`, logging, or the cloud-host arg (it stays; Surface C is forever ip).
- Change `client.py`'s response shape or any public API.

## Decisions

### D1: `ON DELETE SET NULL` on the FK

**Choice:** `allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL`.

**Rationale:** Deleting a node (via `remove`/`abandon`) nulls the task's `allocated_node_id` but preserves the task row and `allocated_ip`. Task history is not lost when a node is removed. The read path today uses `allocated_ip` and is unaffected; when Surface A switches the read path to `allocated_node_id`, a NULL (node gone) maps to `get_session(node_id) is None` → `MACHINE_GONE` — the same semantics as today's `get_session(ip) is None` when the SSH session is gone.

**Alternative considered:** `ON DELETE CASCADE` (delete the task when the node is deleted). Rejected — task history (DONE tasks, completed runs) should survive node removal; the task row is the record of work done, not a child of the node.

**Alternative considered:** No FK (plain `INTEGER`, application enforces). Rejected — the FK catches referential-integrity bugs at the DB level (a task can't reference a non-existent node), and `SET NULL` gives the desired lifecycle semantics.

### D2: `Task.allocate_to(node: Node)` binds both fields

**Choice:** Signature changes from `allocate_to(ip: str)` to `allocate_to(node: Node)`. The method sets `allocated_ip = node.ip` AND `allocated_node_id = node.node_id` in a single `replace(self, ...)` call. The `TaskAlreadyAllocatedError` guard checks `allocated_ip is not None` (unchanged).

**Rationale:** The bind site (`_try_start_on_machine`) always has a `Node` after this change (`_find_free_machines` returns pairs). Taking the `Node` binds both fields atomically — no caller can forget to set one. The guard stays on `allocated_ip` for continuity with `mark_running`'s existing `allocated_ip is None` check (no need to change the guard logic).

**Alternative considered:** `allocate_to(ip: str, node_id: NodeId | None = None)` — keep ip primary, node_id optional. Rejected — it allows callers to bind ip without node_id (the old behavior), which defeats the point of the change and leaves `allocated_node_id` unwritten on ip-only callsites.

**Alternative considered:** `allocate_to(node_id: NodeId)` — bind only `allocated_node_id`, derive `allocated_ip` elsewhere. Rejected — `allocated_ip` stays on the schema and in the read path, so it must be written in the same atomic step; deriving it requires a `Node` lookup at read time, which is the round-trip we're eliminating.

### D3: Backfill all existing tasks in migration 004

**Choice:** Migration 004 runs:
```sql
ALTER TABLE yascheduler_tasks ADD COLUMN allocated_node_id INTEGER
  REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL;
UPDATE yascheduler_tasks t
  SET allocated_node_id = (
    SELECT n.node_id FROM yascheduler_nodes n WHERE n.ip = t.ip
  )
  WHERE t.ip IS NOT NULL;
```
Assumes ip is unique-or-NULL at migration time. Unallocated tasks (`ip IS NULL`) get `allocated_node_id = NULL`.

**Rationale:** Existing RUNNING/DONE tasks get a valid `allocated_node_id` so the column is populated end-to-end from day one. The dup-IP feature is not yet in production use, so the uniqueness assumption holds for current deployments. For the rare case where a legacy DB already has duplicate IPs, the subquery returns one row arbitrarily (Postgres does not guarantee which); those rows get a best-effort `allocated_node_id` and the read path (still ip) is unaffected.

**Alternative considered:** No backfill — leave existing tasks with `allocated_node_id = NULL`. Rejected — leaves the column unpopulated for historical tasks, and Surface A's read-path switch would treat all pre-migration tasks as `MACHINE_GONE` (NULL node_id). Backfilling preserves continuity.

**Alternative considered:** Backfill with a disambiguator (pick `MIN(node_id)` for dup IPs). Rejected — adds complexity for a case that does not occur in current deployments; the simple subquery is sufficient and the read path doesn't use the field yet anyway.

### D4: Read path unchanged — all 6 sites stay ip-keyed

**Choice:** No read site changes in this change. `_task_consumer`, `busy_ips`, `busy_node_ips`, `abandon_node matching`, `show_nodes`, `check_status` all keep reading `allocated_ip`.

**Rationale:** The read path cannot fully migrate until `get_session` can take `node_id` (Surface A — `MachineSession` needs a `node_id` property). Doing half the reads now (e.g. `busy_ips` → `busy_node_ids`) creates a mixed state where some sites use node_id and others use ip, requiring translation at each junction. Cleaner to write the field now, leave all reads on ip, and switch them together in Surface A.

**Alternative considered:** Migrate `busy_ips`/`busy_node_ips` now (they don't need `get_session`). Rejected — `busy_ips` joins `Task.allocated_ip` with `Node.ip` (`all_enabled_nodes = {n.ip: n ... if n.ip not in busy_ips}`); switching to `busy_node_ids` requires also switching `all_enabled_nodes` to a node_id-keyed dict, which is a larger cascade than it appears and is cleaner as part of Surface A's read-path sweep.

### D5: `_find_free_machines` returns `list[(MachineSession, Node)]`, matching by ip

**Choice:** `_find_free_machines` builds `nodes_by_ip = {n.ip: n for n in enabled_nodes}` (dup-IP collapses to one — last wins, same ambiguity as today's `enabled_ips = {n.ip}` set membership), then returns `[(s, nodes_by_ip[s.machine.ip]) for s in list_free() if s.machine.ip in nodes_by_ip and s.machine.ip not in busy_node_ips]`.

**Rationale:** The `Node` is already loaded by `list_enabled()`; carrying it forward to the bind site is free. The session↔node match stays by ip because `MachineSession` does not yet carry `node_id` (Surface A). The dup-IP collapse is the same ambiguity as today — today the code uses `s.machine.ip` and doesn't care which Node it maps to; this change records `allocated_node_id` from one of the duplicates (arbitrary), which is no worse than today and gets fixed when A makes the match unambiguous.

**Alternative considered:** Match by `(ip, port, username)` to disambiguate dup IPs now. Rejected per user direction — keep matching by ip; full disambiguation lands with A.

**Alternative considered:** Return `list[MachineSession]` and have `_try_start_on_machine` look up the `Node` by `session.ip` via a separate `uow.nodes.get(ip)` call. Rejected — reintroduces a round-trip lookup (the same anti-pattern the `deallocate-node-id-identity` change eliminated) and the `Node` is already in hand.

### D6: `allocated_ip` stays everywhere

**Choice:** `allocated_ip` remains on the schema (`yascheduler_tasks.ip`), on `Task`/`NewTask`, in `client.py`'s response, in log lines, and as the cloud-host argument. This change adds `allocated_node_id` alongside it; it does not remove `allocated_ip`.

**Rationale:** `client.py`'s `ip` field is a public API surface (`AGENTS.md`). The cloud-host argument (`clouds.deallocate(cloud, ip)`) is forever ip (Surface C). Logging keeps ip for continuity with existing log scraping. Removing `allocated_ip` would require a schema migration + a 6-site cascade + a public API break — all deferred (and the cloud-host arg never migrates).

## Risks / Trade-offs

- **[Risk] Dup-IP node allocated in the window between this change and Surface A.** `allocated_node_id` is written from `nodes_by_ip[s.machine.ip]`, which collapses duplicates to one arbitrary `Node`. The `allocated_node_id` may not match the Node the task actually runs on. → **Mitigation:** The read path still uses `allocated_ip`, so task dispatch is unaffected (same behavior as today). `allocated_node_id` is not used for dispatch until Surface A, which also fixes the matching ambiguity. No behavioral regression in this window.

- **[Risk] Backfill picks the wrong node_id for a legacy dup-IP row.** If a deployment already has duplicate IPs in `yascheduler_nodes`, the migration's subquery returns one row arbitrarily. → **Mitigation:** The dup-IP feature is not in production use; current deployments have unique IPs. For the rare legacy dup, the read path (ip) is unaffected and `allocated_node_id` is best-effort. Acceptable.

- **[Risk] `allocate_to` signature change is a breaking change for external callers.** `allocate_to(ip: str)` → `allocate_to(node: Node)`. → **Mitigation:** `allocate_to` is a domain-internal method on `Task`; the only callsite is `_try_start_on_machine` (in-repo). The public `Yascheduler` facade does not expose `allocate_to`. No external API break.

- **[Trade-off] `allocated_node_id` is written but not read in this change.** The column is populated for new allocations and backfilled for existing tasks, but every read site still uses `allocated_ip`. → **Mitigation:** This is intentional — the read-path switch is bundled with Surface A to avoid a mixed-state. The column is ready for A to consume; no wasted work.

- **[Trade-off] `nodes_by_ip` dict collapses dup-IP nodes.** `_find_free_machines` returns one `Node` per ip, even if two nodes share that ip. → **Mitigation:** Same ambiguity as today (today uses `enabled_ips = {n.ip}` set membership). Surface A's `node_id`-keyed sessions fix this. No regression.

## Migration Plan

**Schema migration required (migration 004).** Additive and backfilling — non-destructive.

Deploy:
1. `pip install` / `uv sync` the new release.
2. `yainit` (or the test fixture) runs `apply_schema()` (no-op for existing tables — `CREATE TABLE IF NOT EXISTS`) then `apply_migrations()` which applies `004_add_allocated_node_id.sql` (ALTER + UPDATE backfill) in one transaction.
3. Daemon restart picks up the new code; new allocations write `allocated_node_id`; existing tasks have it backfilled.

Rollback:
1. Revert the code change.
2. `ALTER TABLE yascheduler_tasks DROP COLUMN allocated_node_id;` (manual — no down-migration; the migration system is forward-only per `db-migrations` spec).
3. The `allocated_ip` read path is unaffected by rollback — the column is not read until Surface A.

No config change. No public API change. In-flight tasks are unaffected (they keep their `allocated_ip`; the backfill populates `allocated_node_id` for them too).

## Open Questions

(All resolved during design — see Decisions D1-D6. No outstanding open questions.)