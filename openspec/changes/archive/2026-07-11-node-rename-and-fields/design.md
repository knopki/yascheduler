## Context

The `Node` entity and `yascheduler_nodes` table are the oldest part of the
schema, predating cloud provisioning. The table has `ip VARCHAR(15)` — too
narrow for hostnames, FQDNs, or IPv6 — no audit timestamps, no jump-host
fields, no external cloud identifier, and no status enum. The `Task` entity
already has `created_at`/`updated_at` + a `BEFORE UPDATE` trigger (migration
007) and a `TASK_STATUS` enum (migration 008). This change brings `Node` to the
same structural standard.

The `ip` field name is a misnomer: the column holds a hostname or address
string, not necessarily an IP. The rename to `hostname` corrects this and
widens to `VARCHAR(255)`.

There is an active change `fix-tracker-node-link-leak` that touches
`allocate_task.py` and `abandon_node.py` logging lines. This change composes
with it — the `ip`→`hostname` rename in those same log lines is mechanical and
non-overlapping with the tracker shape change.

## Goals / Non-Goals

**Goals:**
- Rename `ip`→`hostname` across all domain entities, ports, SSH/cloud adapters,
  application use cases, CLI renderers, persistence, SQL, and tests.
- Add `created_at`/`updated_at` with a `BEFORE UPDATE` trigger on
  `yascheduler_nodes`, mirroring `yascheduler_tasks`.
- Add `jump_host`/`jump_port`/`jump_username` placeholder fields (schema only,
  not consumed by code yet).
- Add `external_id` backfilled from `hostname` for cloud nodes only, set in
  code only at cloud allocation time.
- Add `NodeStatus(StrEnum)` with a single `OTHER` value, backed by a
  `NODE_STATUS` enum type.
- Add `port` NOT NULL + CHECK constraint (`port > 0 AND port < 65536`).
- Update `MachineBusyError`/`MachineConnectionError` to carry `node_id` as the
  first argument.
- Update JSON output surfaces to emit `"hostname"` + all new fields.

**Non-Goals:**
- `external_id` divergence from `hostname` (future cloud-provider stable ID
  integration is a separate change requiring provider API calls).
- Consuming `jump_host`/`jump_port`/`jump_username` in code (placeholder
  fields only).
- Adding node lifecycle states beyond `OTHER` (future states will replace
  `OTHER`; the enum is a structural placeholder).
- `allocated_tasks_ids` on `Node` (deferred — explored and set aside).
- Changing the AiiDA plugin contract (it uses `_render_default` only — no node
  fields, unaffected).

## Decisions

### D1: Rename `ip`→`hostname` everywhere, including runtime types

Rename `ip`→`hostname` on `Node`, `NewNode`, `ConnectedMachine`,
`MachineSession.ip`, `SSHMachineSession.ip`/`_ip`, `MachineBusyError.ip`,
`MachineConnectionError.ip`, all SQL files, and all call sites.

**Alternative considered:** rename only `Node`/`NewNode` and leave
`ConnectedMachine.ip`/`MachineSession.ip` as `ip` (semantic distinction:
"hostname" = configured address, "ip" = live transport address). Rejected —
the user confirmed a mechanical rename across all types. Keeping a split would
create a naming inconsistency at the `ConnectedMachine(ip=node.hostname)`
construction site and in every log line.

### D2: `MachineBusyError`/`MachineConnectionError` gain `node_id` first

Constructors become:
```
MachineBusyError(node_id: NodeId, hostname: str)
MachineConnectionError(node_id: NodeId, hostname: str, reason: str)
```
Message formats: `"machine ({node_id}) at {hostname} is busy"` and
`"cannot connect to machine ({node_id}) at {hostname}: {reason}"`.

Both call sites already have `node_id` in scope:
`ConnectedMachine.occupy()` has `self.node_id`; `SSHMachineRepository._connect_impl`
has `node.node_id`.

### D3: `external_id` backfill — cloud nodes only

Migration backfills `external_id = hostname` only for rows where
`cloud IS NOT NULL AND hostname <> ''`. Static nodes (manually added) keep
`external_id = NULL`. In code, `external_id` is set alongside `hostname` only
at `CloudProvisionerImpl.allocate`:
```python
replace(node, hostname=ip_addr, external_id=ip_addr, cloud=adapter.name, ...)
```
The `_add_node` static path does NOT set `external_id`.

**Rationale:** future intent is `external_id` = cloud provider's stable VM
identifier (diverging from `hostname`). That requires provider API changes and
is out of scope. The backfill + code sync establish the column without the
divergence.

### D4: `NodeStatus` enum — single value `OTHER`, `StrEnum` via `shared/compat`

```python
class NodeStatus(StrEnum):
    OTHER = "OTHER"
```
Value `"OTHER"` matches the `TASK_STATUS` convention (enum label == name,
`.name`-based DB lookup via `NodeStatus[row["status"]]`). `StrEnum` is sourced
via `shared/compat.py` with a version branch:
```python
if sys.version_info < (3, 11):
    from typing_extensions import StrEnum
else:
    from enum import StrEnum
```
`typing-extensions` is already a conditional dependency
(`python_version < '3.11'`). No new runtime dependency.

### D5: Port CHECK — `CHECK (port > 0 AND port < 65536)`

Excludes port 0 (not meaningful for explicit SSH connections). Upper bound
65536 exclusive = 65535 inclusive. Same pattern applied to `jump_port`.

### D6: `count_by_status.sql` — `COUNT(node_id)`

Was `COUNT(ip)`. After rename, `COUNT(node_id)` is semantically correct
(counts rows by the primary key) and avoids any column-name dependency.

### D7: JSON surfaces — `"hostname"` + all new fields

Three JSON output surfaces change:

| surface | current key | new key | new fields added |
|---|---|---|---|
| `yanodes --json` | `"ip"` | `"hostname"` | `jump_host`, `jump_port`, `jump_username`, `external_id`, `status`, `created_at`, `updated_at` |
| `yastatus --json` (node object) | `"ip"` | `"hostname"` | `jump_host`, `jump_port`, `jump_username`, `external_id`, `status`, `created_at`, `updated_at` |
| `Yascheduler` client (node dict) | `"ip"` | `"hostname"` | same set |

AiiDA uses `_render_default` (`<task_id>   <STATUS_NAME>`) — no node fields.
The AiiDA plugin is unaffected.

### D8: Migration 012 — multi-step, forward-only

Single migration file `012_node_rename_and_fields.sql` performing:
1. `RENAME COLUMN ip TO hostname`
2. `ALTER COLUMN hostname TYPE VARCHAR(255)`
3. `ADD COLUMN created_at/updated_at` + trigger
4. `ADD COLUMN jump_host/jump_port/jump_username`
5. `ADD COLUMN external_id` + backfill for cloud rows
6. `CREATE TYPE NODE_STATUS` + `ADD COLUMN status`
7. `ALTER COLUMN port SET NOT NULL` + `ADD CHECK`
8. `last_migration` constant bumped `'011'`→`'012'`

Follows the migration edit procedure (3 edits): create file, bump constant,
update snapshot DDL in `schema.sql`.

## Risks / Trade-offs

- **Public API break** (JSON key `ip`→`hostname`): external consumers parsing
  `yanodes --json` or `yastatus --json` must update their parsers. Mitigated
  by: AiiDA (the only known external consumer) uses `_render_default` only.
  The break is intentional and documented in the proposal.

- **`jump_host`/`jump_port`/`jump_username`/`NodeStatus` are placeholder
  fields** with no code consumption yet. YAGNI risk — but adding them in the
  same migration as the rename is cheaper than a follow-up migration, and the
  user explicitly requested them as forward-looking placeholders.

- **`external_id` backfill copies `hostname` for cloud nodes** — until the
  future divergence change, `external_id` is a redundant copy. Acceptable as a
  structural setup for the future cloud-provider ID integration.

- **Test churn** (~100+ `.ip` references in tests): mechanical rename. Low
  risk, high volume. Parallelizable.