# Proposal: task-schema-and-entity-cleanup

## Why

The `yascheduler_tasks` table and the `Task` domain entity carry accumulated
cruft and inconsistencies: a redundant `allocated_ip` column that duplicates the
`allocated_node_id` foreign key (the canonical allocation signal since the
ssh-rekey-node-id change), a `label` column name that is a PostgreSQL keyword,
a `status` column stored as `SMALLINT` with no database-level constraint
guaranteeing valid values, and no `created_at`/`updated_at` audit timestamps.
Cleaning these up in one change keeps the schema and entity coherent and makes
the database enforce the task-status domain.

## What Changes

- **Add** `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` and
  `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` columns to
  `yascheduler_tasks`, with a `BEFORE UPDATE` trigger function that sets
  `updated_at = NOW()` on every row update (PostgreSQL has no MySQL-style
  `ON UPDATE` clause; a trigger is the standard mechanism).
- **Add** `created_at: datetime` and `updated_at: datetime` fields to the
  domain `Task` entity (DB-generated; absent from `NewTask`).
- **Add** `created_at` and `updated_at` (ISO-8601 strings) to the
  `yastatus --json` output object.
- **BREAKING — Remove** the `allocated_ip` field from the domain `Task` and
  `NewTask` entities and the `ip` column from `yascheduler_tasks`. The
  `allocate_to` and `mark_running` guards switch from
  `self.allocated_ip is not None` to `self.allocated_node_id is not None`
  (the canonical allocation signal). This is an accepted breaking change to the
  `yastatus --json` and `Yascheduler` facade wire formats.
- **BREAKING — Change** the `yastatus --json` output object: drop the flat
  `allocated_ip`/`port`/`cloud` fields; add a nested `node` object
  `{ip, port, username, cloud}` (or `null` when the task has no allocated
  node), built by joining `nodes_by_id.get(task.allocated_node_id)`.
- **BREAKING — Change** the `yastatus -i` (info) output: replace the `ip=...`
  field with `node_id=...` (the task's `allocated_node_id`).
- **BREAKING — Change** the `Yascheduler` client facade `queue_get_tasks*`
  return shape: drop the flat `ip` and `cloud` keys; add a nested `node`
  object `{ip, port, username, cloud}` (or `null`). `{task_id, label, status,
  metadata}` are unchanged.
- **Rename** the `yascheduler_tasks.label` column to `title` (`label` is a
  PostgreSQL keyword; `title` is not). The domain field `Task.label` and the
  JSON/dict key `"label"` are unchanged — only the database column name
  changes, with a param-name rename in the persistence layer
  (`label=task.label` → `title=task.label`).
- **Change** the `yascheduler_tasks.status` column type from `SMALLINT` to a
  PostgreSQL enum `CREATE TYPE task_status AS ENUM ('TO_DO', 'RUNNING',
  'DONE')`, with a `USING CASE` migration that maps the existing integer
  values (0/1/2) to the enum labels. The domain `TaskStatus` remains a Python
  `IntEnum` (`TO_DO=0, RUNNING=1, DONE=2`); the database now stores the enum
  label (string), and the persistence layer writes `task.status.name` and
  reads `TaskStatus[row["status"]]` (name lookup). The external API numeric
  value is preserved: `yastatus --json` still emits `task.status.name` (the
  string label, unchanged), `client._task_to_dict` still emits the `IntEnum`
  member (`.value` = 0/1/2, unchanged), and the webhook payload still emits
  `status.value` (int, unchanged).
- **Rename** the `PostgresTaskRepository.list_ids_by_ip_and_status` method and
  its SQL file `get_ids_by_ip_and_status.sql` to
  `list_ids_by_node_id_and_status` / `get_ids_by_node_id_and_status.sql`,
  filtering by `allocated_node_id = :node_id` instead of `ip = :ip`. Both
  call sites in `entrypoints/cli/manage_node.py` (`_remove_node_hard`,
  `_remove_node_soft`) already hold a fully-resolved `Node` with
  `node.node_id`.
- **Add** four migrations: `006_rename_label_to_title.sql`,
  `007_add_created_updated_at.sql` (+ trigger function + trigger),
  `008_status_to_enum.sql`, `009_drop_allocated_ip.sql`. The `schema.sql`
  snapshot and its `last_migration` constant are updated to reflect the final
  state (`last_migration` becomes `'009'`).

## Capabilities

**New Capabilities:** none.

**Modified Capabilities:**
- `domain-entities` — `Task`/`NewTask` field lists (drop `allocated_ip`, add
  `created_at`/`updated_at` to `Task`), `allocate_to`/`mark_running` guard
  predicates switch to `allocated_node_id`.
- `domain-ports` — `TaskRepository` Protocol method
  `list_ids_by_ip_and_status(ip, status)` →
  `list_ids_by_node_id_and_status(node_id, status)` (the port-level rename
  matching the `postgres-persistence` adapter rename).
- `postgres-persistence` — `insert.sql`/`update_by_id.sql`/`get_by_id.sql`/
  `list_by_status.sql`/`list_by_jobs.sql` column lists (drop `ip`, add
  `created_at`/`updated_at` to reads, rename `label`→`title`), `_row_to_task`
  mapping (name lookup for status, no `allocated_ip`, `created_at`/`updated_at`
  reads), write path emits `status.name` (string), `list_by_status` SQL cast
  to `task_status[]`, `count_by_status` caller switches to `TaskStatus[row["status"]]`,
  `list_ids_by_ip_and_status` → `list_ids_by_node_id_and_status`.
- `db-migrations` — four new migrations (006–009) with ordering and rollback
  considerations.
- `postgres-schema-apply` — `last_migration` constant `'005'` → `'009'`;
  `schema.sql` snapshot reflects final table shape.
- `cli` — `yastatus --json` object shape (flat `allocated_ip`/`port`/`cloud` →
  nested `node` + `created_at`/`updated_at`), `_render_info` `ip` → `node_id`,
  stale `allocated_ip` references in `yanodes` section cleaned up.
- `package-facades` — `Yascheduler` query dict shape (flat `ip`/`cloud` →
  nested `node`), `query_tasks` use case return type changes from
  `list[Task]` to `tuple[list[Task], dict[NodeId, Node]]` (the facade unpacks
  and projects the nested `node`).
- `use-cases` — `query_tasks` return type change
  (`list[Task]` → `tuple[list[Task], dict[NodeId, Node]]`); the use case
  batch-loads nodes via `uow.nodes.get_by_ids` inside its existing single UoW.

## Impact

- **Code**: `yascheduler/domain/model.py` (`Task`, `NewTask`, `TaskStatus`
  stays IntEnum, guard predicates), `yascheduler/infra/persistence/postgres.py`
  (`_row_to_task`, `save`, `insert`, `list_by_status`, `count_by_status`,
  `list_ids_by_node_id_and_status`), `yascheduler/infra/persistence/sql/task/*.sql`
  (all task SQL files), `yascheduler/entrypoints/cli/check_status.py`
  (`_render_info`, `_render_json`, `_render_view`), `yascheduler/entrypoints/client.py`
  (`_task_to_dict`, `queue_get_tasks_async`), `yascheduler/application/query_tasks.py`
  (return type + node batch-load), `yascheduler/entrypoints/cli/manage_node.py`
  (`_remove_node_hard`, `_remove_node_soft` call sites), `yascheduler/infra/persistence/sql/schema.sql`
  + new migration files.
- **APIs (breaking)**: `yastatus --json` wire format; `Yascheduler.queue_get_tasks*`
  return dict shape. The webhook payload (`{task_id, status, custom_params}`) is
  unchanged. The AiiDA scheduler plugin parses `yastatus` default mode
  (`task_id   STATUS`) and is unaffected; confirm during implementation that no
  AiiDA code reads the dropped JSON keys.
- **Database**: four additive/rename/transform/drop migrations; the
  `yascheduler_tasks` table gains two columns, renames one, changes one
  column type, and loses one column. The `status` enum type is created at
  migration 008. A trigger function + trigger are installed at migration 007.
- **Dependencies**: none added.
- **Tests**: unit tests for `query_tasks` (new return shape), `count_by_status`
  (name lookup), `_row_to_task` (enum read, no `allocated_ip`, timestamps);
  integration tests for migrations 006–009 and the enum array binding;
  e2e tests asserting on `task.allocated_ip` must be rewritten to assert on
  `task.allocated_node_id` + node lookup, or on the new `node.ip` JSON field.