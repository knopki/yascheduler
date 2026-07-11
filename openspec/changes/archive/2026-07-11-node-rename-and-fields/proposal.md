## Why

The `Node` domain entity and `yascheduler_nodes` DB table predate the cloud
provisioning layer and carry a minimal column set: the `ip` column is a
`VARCHAR(15)` (too narrow for hostnames/FQDNs/IPv6), the `port` lacks a NOT
NULL + CHECK constraint, there are no audit timestamps (`created_at`/
`updated_at`), no jump-host connection parameters (`jump_host`/`jump_port`/
`jump_username`), no external cloud-provider identifier (`external_id`), and
no node-status enum. The `ip` field name is also a misnomer — the column holds
a hostname/address string, not necessarily an IP, and `VARCHAR(15)` cannot
fit a hostname or an IPv6 address. This change renames `ip`→`hostname`, widens
the column, adds the missing fields, and introduces a `NodeStatus` enum as a
placeholder for future node lifecycle states — all mirroring the
already-established `Task` entity shape.

## What Changes

- **BREAKING**: Rename `ip`→`hostname` on `Node`, `NewNode`,
  `ConnectedMachine`, `MachineSession.ip`, `SSHMachineSession.ip`,
  `MachineBusyError.ip`, `MachineConnectionError.ip`, all 12 `node/*.sql`
  files, and all Python call sites (~88 references in `yascheduler/`).
- **BREAKING**: Rename the JSON key `"ip"`→`"hostname"` in the three public
  JSON output surfaces: `yastatus --json`, `yanodes --json`, and the
  `Yascheduler` Python client `node` dict. AiiDA uses only the
  `_render_default` path (`<task_id>   <STATUS_NAME>`) — no `node` fields,
  so the AiiDA scheduler plugin is unaffected.
- Widen the DB `ip` column from `VARCHAR(15)` to `VARCHAR(255)` via rename
  to `hostname`.
- Add `NOT NULL` + `CHECK (port > 0 AND port < 65536)` to the `port` column.
- Add `created_at`/`updated_at` (`TIMESTAMPTZ NOT NULL DEFAULT NOW()`) with a
  `BEFORE UPDATE` trigger mirroring `yascheduler_tasks` (migration 007).
- Add `jump_host` (`VARCHAR(255)`, nullable), `jump_port` (`INTEGER NOT NULL
  DEFAULT 22` + `CHECK 0-65535`), `jump_username` (`VARCHAR(255) NOT NULL
  DEFAULT 'root'`). Not consumed by code yet — placeholder fields.
- Add `external_id` (`VARCHAR(255)`, nullable). Backfilled from `hostname`
  at migration time **only for rows with a non-empty `cloud`**. Set in code
  alongside `hostname` **only at cloud allocation time**
  (`CloudProvisionerImpl.allocate`). Future intent: `external_id` becomes the
  cloud-provider's stable VM identifier, diverging from `hostname` — but
  that divergence is explicitly out of scope (requires provider API changes).
- Add `NodeStatus(StrEnum)` with a single value `OTHER = "OTHER"`, backed by
  a new `NODE_STATUS` PostgreSQL enum type. Placeholder for future node
  lifecycle states; `OTHER` will eventually be replaced. Threaded through
  `shared/compat.py` (version-branch: `enum.StrEnum` on 3.11+,
  `typing_extensions.StrEnum` below 3.11).
- `MachineBusyError` and `MachineConnectionError` constructors gain a
  `node_id: NodeId` first argument, becoming
  `MachineBusyError(node_id, hostname)` and
  `MachineConnectionError(node_id, hostname, reason)`. Message format:
  `"machine ({node_id}) at {hostname} is busy"` and
  `"cannot connect to machine ({node_id}) at {hostname}: {reason}"`.
- `count_by_status.sql`: `COUNT(ip)`→`COUNT(node_id)`.

## Capabilities

### New Capabilities

<!-- None — this change modifies existing capabilities, introduces no new capability. -->

### Modified Capabilities

- `domain-entities`: `Node` and `NewNode` gain `hostname` (renamed from
  `ip`), `jump_host`/`jump_port`/`jump_username`, `external_id`,
  `status: NodeStatus`, `created_at`/`updated_at`. `ConnectedMachine.ip`
  renamed to `ConnectedMachine.hostname`. The `NodeStatus` enum is introduced.
- `domain-exceptions`: `MachineBusyError` and `MachineConnectionError` gain a
  `node_id: NodeId` first constructor argument and rename `ip`→`hostname`.
- `domain-ports`: `MachineSession.ip` property renamed to `hostname`;
  `CloudProvisioner` docstring references `node.hostname` instead of
  `node.ip`.
- `ssh-infrastructure`: `SSHMachineSession.ip`/`_ip` renamed to
  `hostname`/`_hostname`; `SSHMachineRepository._connect_impl` reads
  `node.hostname` instead of `node.ip`; `MachineConnectionError` construction
  gains `node.node_id`.
- `postgres-persistence`: `PostgresNodeRepository` binds/reads `hostname`
  and the new columns; all 12 `node/*.sql` files rename `ip`→`hostname`;
  `count_by_status.sql` uses `COUNT(node_id)`.
- `cli`: `yanodes --json` and `yastatus --json` emit `"hostname"` instead of
  `"ip"` plus all new node fields; table column header `IP`→`HOSTNAME`;
  `manage_node` reads `node.hostname`; `Yascheduler` client `node` dict key
  `ip`→`hostname` + new fields.
- `db-migrations`: migration 012 renames `ip`→`hostname`, widens to
  `VARCHAR(255)`, adds `created_at`/`updated_at` + trigger, `jump_host`/
  `jump_port`/`jump_username`, `external_id` (backfilled for cloud rows),
  `NODE_STATUS` enum + `status` column, `port` NOT NULL + CHECK;
  `last_migration` constant bumped to `'012'`.
- `config-value-objects`: `shared/compat.py` gains `StrEnum` re-export
  (version-branch).
- `use-cases`: `deallocate_node`/`deallocate_nodes` and `abandon_node` log
  lines reference `node.hostname` instead of `node.ip`.

## Impact

- **Code**: `yascheduler/domain/model.py` (Node, NewNode, ConnectedMachine,
  NodeStatus enum), `yascheduler/domain/exceptions.py` (MachineBusyError,
  MachineConnectionError), `yascheduler/domain/ports.py` (MachineSession,
  CloudProvisioner docstring), `yascheduler/infra/ssh/session.py`
  (SSHMachineSession), `yascheduler/infra/ssh/repository.py`
  (_connect_impl, MachineConnectionError construction),
  `yascheduler/infra/ssh/operations/*.py` (session.ip→session.hostname in
  logs), `yascheduler/infra/cloud/manager.py` (node.ip→node.hostname,
  replace(node, hostname=..., external_id=...)),
  `yascheduler/application/allocate_task.py`,
  `yascheduler/application/abandon_node.py`,
  `yascheduler/application/deallocate_nodes.py`,
  `yascheduler/application/orchestrator.py`,
  `yascheduler/infra/persistence/postgres.py` (insert/update/_row_to_node),
  `yascheduler/infra/persistence/sql/node/*.sql` (12 files),
  `yascheduler/infra/persistence/sql/schema.sql` (last_migration constant),
  `yascheduler/shared/compat.py` (StrEnum),
  `yascheduler/entrypoints/client.py` (JSON key),
  `yascheduler/entrypoints/cli/check_status.py`,
  `yascheduler/entrypoints/cli/show_nodes.py`,
  `yascheduler/entrypoints/cli/manage_node.py`.
- **DB migration**: new file
  `yascheduler/infra/persistence/sql/migrations/012_node_rename_and_fields.sql`;
  `schema.sql` `last_migration` constant bumped `'011'`→`'012'`.
- **Tests**: ~100+ references to `.ip` across `tests/unit/` and
  `tests/integration/` — mechanical rename to `.hostname`; exception
  assertion sites gain `node_id` checks; JSON assertions update key
  `ip`→`hostname` and add new field assertions.
- **Public API**: `Yascheduler` client `node` dict key `ip`→`hostname` +
  new keys (`jump_host`, `jump_port`, `jump_username`, `external_id`,
  `status`, `created_at`, `updated_at`). `yastatus --json` output expands
  from 6 fields to 16 fields (adding a nested `node` object with 10 fields
  including `hostname` + all new node fields). `yanodes --json` output shape
  changes identically (`"ip"`→`"hostname"` + 7 new fields). AiiDA plugin
  unaffected (uses `_render_default` only — no node fields).
- **Dependencies**: no new runtime dependencies. `StrEnum` sourced via
  `typing_extensions` (already a conditional dep for `python_version < '3.11'`).