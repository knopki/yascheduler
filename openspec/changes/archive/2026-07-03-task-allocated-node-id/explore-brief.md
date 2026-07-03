# Explore Brief — task-allocated-node-id

## What we're doing

Add `allocated_node_id` to `yascheduler_tasks` (nullable FK to `yascheduler_nodes(node_id)` with `ON DELETE SET NULL`) and write it at the single Task↔Node bind site (`Task.allocate_to`). This is Surface E of the ip→NodeId migration. The read path stays ip-keyed for now; a later change (`ssh-rekey-node-id`, Surface A) switches the read path.

## Why this surface and sequence

`Task.allocated_ip` is the schema field binding a Task to the Node it runs on. Removing/replacing it cascades through 6 read sites. But `client.py` keeps `ip` (no breaking change to public API), so this is **additive**: add `allocated_node_id` alongside `allocated_ip`, write both at the bind site, leave reads on ip until Surface A lands.

Coupling: `_task_consumer`'s `get_session(task.allocated_ip)` is the read-site that blocks Surface A. Surface A rekeys `_sessions` to NodeId; `get_session` switches to `allocated_node_id`. So E must land first (write the field), then A (switch the read).

## Alternatives rejected

- **Surface A first (SSH rekey)**: blocked on E. `get_session(ip)` cannot switch to `get_session(node_id)` until Task carries `allocated_node_id`. Deadlock if A goes first.
- **E + A as one change**: cleanest but largest; the triangle Task↔Node↔Session flips simultaneously. Deferred — E is the smaller, additive step that unblocks A.
- **E with full read-cascade now**: would switch all 6 read sites to `allocated_node_id` in this change. But `get_session` still needs ip (no node_id on session until A), so the read path can't fully migrate. Doing half the reads now creates a mixed state. Cleaner to leave all reads on ip and switch them together in A.
- **E with `(ip, port, username)` session↔node matching to disambiguate dup IPs now**: rejected per user — keep matching by ip (same ambiguity as today). Full disambiguation lands with A (session carries node_id).

## Decisions (settled during explore)

- **D1: `ON DELETE SET NULL` on the FK** — deleting a node nulls `allocated_node_id`; tasks remain. No cascade delete of task history.
- **D2: `Task.allocate_to(node: Node)`** — binds both `allocated_ip = node.ip` and `allocated_node_id = node.node_id` in one call. Signature changes from `allocate_to(ip: str)`. The single callsite (`_try_start_on_machine`) is updated. Future: may narrow to `NodeId` once `allocated_ip` is removed (post-A).
- **D3: Backfill all existing tasks in the migration** — assume ip is unique (or NULL) at migration time. `UPDATE yascheduler_tasks t SET allocated_node_id = (SELECT node_id FROM yascheduler_nodes n WHERE n.ip = t.ip) WHERE t.ip IS NOT NULL`. Unallocated (ip IS NULL) tasks get NULL.
- **D4: Read path unchanged in this change** — all 6 read sites (`_task_consumer get_session`, `busy_ips`, `abandon_node matching`, `show_nodes`, `check_status`, `_find_free_machines busy_node_ips`) keep using `allocated_ip`. They switch in Surface A.
- **D5: `allocated_ip` stays** — on the schema, on `Task`/`NewTask`, in `client.py`, in logging, in the cloud-host arg (Surface C, forever ip). This change adds; it does not remove.
- **D6: `_find_free_machines` returns `list[(MachineSession, Node)]`** — carries the `Node` forward so `_try_start_on_machine` has `node.node_id` to write. Matching stays by ip: `nodes_by_ip = {n.ip: n for n in enabled_nodes}` (dup-IP collapses to one — same ambiguity as today). Full disambiguation lands with A.

## Labels / mapping tables

### Schema

| Column | Type | Constraint | Notes |
|---|---|---|---|
| `yascheduler_tasks.allocated_node_id` | `INTEGER` | `REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL` | nullable; new; backfilled |
| `yascheduler_tasks.ip` (existing) | `VARCHAR(15)` | (none) | stays; renamed to `allocated_ip` in domain only |

### Migration 004

```sql
ALTER TABLE yascheduler_tasks
  ADD COLUMN allocated_node_id INTEGER
  REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL;

UPDATE yascheduler_tasks t
  SET allocated_node_id = (
    SELECT n.node_id FROM yascheduler_nodes n WHERE n.ip = t.ip
  )
  WHERE t.ip IS NOT NULL;
-- assumes ip unique-or-NULL at migration time (subquery returns ≤1 row)
-- ip IS NULL → allocated_node_id stays NULL (unallocated TO_DO)
```

### SQL files (5 + migration + schema.sql)

| File | Change |
|---|---|
| `migrations/004_add_allocated_node_id.sql` | new; ALTER + UPDATE backfill |
| `schema.sql` | add `allocated_node_id` column to `yascheduler_tasks`; bump `last_migration` `'003'`→`'004'` |
| `task/insert.sql` | add `node_id` to INSERT cols + RETURNING |
| `task/update_by_id.sql` | add `node_id = :node_id` to SET |
| `task/get_by_id.sql` | add `node_id` to SELECT |
| `task/list_by_status.sql` | add `node_id` to SELECT |
| `task/list_by_jobs.sql` | add `node_id` to SELECT |

### Domain model (`model.py`)

| Symbol | Change |
|---|---|
| `NewTask.allocated_node_id` | new field: `NodeId \| None = None` |
| `Task.allocated_node_id` | new field: `NodeId \| None = None` |
| `Task.allocate_to(ip: str)` | signature → `allocate_to(node: Node)`; sets both `allocated_ip` and `allocated_node_id` |

### Application (`allocate_task.py`)

| Function | Change |
|---|---|
| `_find_free_machines` | return `list[(MachineSession, Node)]`; `nodes_by_ip = {n.ip: n}`; ip matching unchanged |
| `_try_start_on_machine` | takes `(session, node)`; calls `task.allocate_to(node)`; log adds `node_id=%s` |
| `_allocate_free_machine` | iterates `(session, node)` pairs; passes both to `_try_start_on_machine` |

### Postgres adapter (`postgres.py`)

| Method | Change |
|---|---|
| `insert` | bind `node_id=new_task.allocated_node_id.value` (or None) |
| `save` | bind `node_id=task.allocated_node_id.value` (or None) |
| `_row_to_task` | read `row["node_id"]` → `NodeId(int(...))` if present else None |

### Read path — UNCHANGED (deferred to Surface A)

| Site | Stays ip-keyed |
|---|---|
| `_task_consumer` `get_session(task.allocated_ip)` | yes |
| `busy_ips = {t.allocated_ip}` | yes |
| `busy_node_ips = {t.allocated_ip}` | yes |
| `abandon_node` `matching = [t if t.allocated_ip == node.ip]` | yes |
| `show_nodes` `tasks_by_ip.get(node.ip)` | yes |
| `check_status` `nodes_by_ip.get(task.allocated_ip)` | yes |
| `client.py` `"ip": t.allocated_ip` | yes (forever) |

## Cross-module data flow

```
WRITE PATH (this change):
  list_enabled() ──list[Node]──▶ _find_free_machines
                                   │ nodes_by_ip = {n.ip: n}  (ip matching, same as today)
                                   ▼
                         list[(MachineSession, Node)]
                                   │
                                   ▼
  _try_start_on_machine(session, node):
    task = task.allocate_to(node)        ← sets allocated_ip + allocated_node_id
    uow.tasks.save(task)                 ← writes both columns
    uow.commit()

READ PATH (unchanged, ip-keyed):
  _task_consumer:  get_session(task.allocated_ip)   ← still ip
  busy_ips:        {t.allocated_ip}                  ← still ip

FK lifecycle:
  node removed → allocated_node_id = NULL (ON DELETE SET NULL)
                 allocated_ip = "10.0.0.5" (stays for logging/client.py)
```

## Open questions (settled)

1. ON DELETE behavior → SET NULL (D1).
2. allocate_to signature → takes Node (D2).
3. Backfill existing tasks → yes, assume unique ip at migration time (D3).
4. Read path in scope → no, deferred to A (D4).
5. allocated_ip removed → no, stays (D5).
6. session↔node matching → stays by ip (D6, per user).

## Risk window

Between this change and Surface A: `allocated_node_id` is written for new allocations but the read path still uses ip. For a dup-IP node allocated in this window, `allocated_node_id` may point at one of the duplicate rows (ambiguous, same as today's ip-based matching). No behavioral regression — the read path doesn't use the new field yet. Surface A fixes the matching ambiguity.