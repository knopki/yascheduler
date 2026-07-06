# Proposal: drop-task-context-entity

## Why

The `yascheduler_tasks` table stores the bulk of a task's domain state inside a single
`metadata JSONB` column, and the domain layer models that JSONB as a separate
`TaskContext` value object accessed via `task.context.X`. This dual structure is both
costly and misleading: every read of `engine`, `remote_folder`, `local_folder`,
`webhook_url`, `webhook_custom_params`, or `error` pays a `task.context.` hop for no
behavioral gain, and the `metadata` blob hides the typed schema behind stringly-typed
keys. Extracting these fields into typed columns and folding `TaskContext` into `Task`
removes the indirection, makes the schema self-describing, and enables normal SQL
filtering/indexing on the fields that matter operationally (`engine`, `remote_folder`,
`error`). The change also dissolves a domain entity that earned its keep only as a
JSONB-shaped bag — pure simplification.

## What Changes

- **BREAKING (internal schema)**: `yascheduler_tasks` drops the `metadata JSONB`
  column and gains seven typed columns — `engine VARCHAR(64) NOT NULL`,
  `remote_folder VARCHAR(1024)`, `local_folder VARCHAR(1024)`,
  `webhook_url VARCHAR(2048)`, `error TEXT`, `webhook_custom_params JSONB NOT NULL
  DEFAULT '{}'::jsonb`, `extra JSONB NOT NULL DEFAULT '{}'::jsonb` — via migration 010.
  Existing rows are backfilled from `metadata` and `metadata` is dropped.
- **BREAKING (internal domain model)**: the `TaskContext` and `TaskContextOverrides`
  value objects, plus `to_metadata` / `from_metadata` / `_get_opt_str` / `with_context`,
  are removed. `Task` and `NewTask` gain the typed fields directly. The nested
  `context.replace(error=reason)` in `Task.fail(reason)` and `Task.reject(reason)`
  simplifies to a direct `replace(self, status=DONE, error=reason)` (status-validation
  guards `TaskNotRunningError` / `TaskNotTodoError` unchanged). `Task.with_event` reads
  `self.webhook_url` / `self.webhook_custom_params` directly.
- New `Task` methods express the two real mutation sites explicitly:
  `with_remote_folder(remote_folder)` (submit-time remote path assignment) and
  `with_download_results(*, local_folder, remote_folder)` (consume-time post-download
  update). `with_download_results` does NOT update `extra` — after extraction `extra`
  carries only input-file payloads and is never touched by the download path (the
  legacy `extra_updates` merge in `consume_task` was always a no-op and is removed).
- The download-error string gains a format contract: failures originating in
  `consume_task` write `"Download error: <path>: <msg>, <path>: <msg>"` (combined
  permanent + transient, behavior preserved; entries with `path=None` render as bare
  `"<msg>"`, though in practice `path` is always a string); the two non-download
  failure sites (`allocate_task` reject, `orchestrator` fail) keep their bare
  human-string reasons. `NULL` means no error. Legacy `str(dict)` error values in
  existing rows are passed through by the migration unchanged.
- The dead `update_meta.sql` file is deleted.
- The public surface is preserved: `queue_get_tasks*` dict shape
  `{task_id, label, status, metadata, node}` is unchanged — `_task_to_dict`
  reconstructs the flat `metadata` dict from the typed fields plus `extra` at read
  time. `Yascheduler` public API, CLI commands, INI config format, and the AiiDA
  scheduler entrypoint are untouched.

## Capabilities

Modified capabilities (delta specs required — spec-level behavior changes, not
implementation details):

- **domain-entities** — `Task` / `NewTask` shape, removal of `TaskContext` /
  `TaskContextOverrides`, new `with_remote_folder` / `with_download_results` methods,
  simplified `fail` / `reject`, `with_event` reading typed fields, error column format
  contract.
- **domain-engine-types** — `Engine.validate_inputs(extra: Mapping[str, object])`
  (was `validate_inputs(ctx: TaskContext)`); the engine reads input-file payloads
  from the task's `extra` dict directly, no `TaskContext` indirection.
- **domain-events-and-dispatch** — `Task.with_event` and the use-case-to-event
  mapping read `task.webhook_url` / `task.webhook_custom_params` / `task.engine`
  directly (was `task.context.X`); no `TaskContext` indirection in the event path.
- **postgres-persistence** — `_row_to_task` reads typed columns; `insert` / `save`
  bind typed columns instead of serialized `metadata`; `load_query` column lists for
  `insert` / `update_by_id` / `get_by_id` / `list_by_status` / `list_by_jobs`.
- **postgres-schema-apply** — `schema.sql` column set and `last_migration` constant.
- **db-migrations** — migration 010 extracting typed columns from `metadata`.
- **package-facades** — `_task_to_dict` reconstructs the flat `metadata` dict from
  typed fields plus `extra`.
- **use-cases** — `submit_task` extracts typed fields from the caller metadata dict;
  `consume_task` uses `with_download_results`, deletes the `extra_updates` block, and
  applies the new download-error format contract.
- **cli** — `check_status` reads `task.engine` / `task.local_folder` /
  `task.remote_folder` instead of `task.context.X`.
- **ssh-infrastructure** — `deployment.py` reads `task.extra` / `task.remote_folder`
  instead of `task.context.X`.
- **testing-unit**, **test-db-integration**, **e2e-testing** — test fixtures and
  assertions updated to the new `Task` / `NewTask` shape (no `TaskContext(...)`
  construction; reads via `task.X` not `task.context.X`). Test updates are not a design
  blocker (user-explicit), but the specs tracking test shape carry deltas.

No new capabilities are introduced.

## Impact

- **Code**: `yascheduler/domain/model.py` (TaskContext removal, Task/NewTask reshape,
  new methods), `yascheduler/domain/__init__.py` (drop `TaskContext` export),
  `yascheduler/infra/persistence/postgres.py` (`_row_to_task`, `insert`, `save`),
  `yascheduler/infra/persistence/sql/schema.sql` (`last_migration='010'`, column set),
  `yascheduler/infra/persistence/sql/task/{insert,update_by_id,get_by_id,list_by_status,list_by_jobs}.sql`
  (column lists), `yascheduler/infra/persistence/sql/migrations/010_extract_metadata_columns.sql`
  (new), `yascheduler/infra/persistence/sql/task/update_meta.sql` (deleted),
  `yascheduler/application/{submit_task,consume_task,allocate_task,orchestrator}.py`,
  `yascheduler/infra/ssh/operations/deployment.py`, `yascheduler/entrypoints/client.py`
  (`_task_to_dict`), `yascheduler/entrypoints/cli/check_status.py`.
- **DB**: migration 010 — additive (seven new columns, backfilled from `metadata`),
  then `metadata` dropped. Requires the post-009 schema (committed at `d7fc8b3`).
  Existing rows keep their `error` values verbatim (legacy `str(dict)` format preserved
  by passthrough).
- **APIs**: internal domain model only. `Yascheduler` public API, CLI dict shape, INI
  config, AiiDA entrypoint unchanged.
- **Dependencies**: none added.
- **GRACE-lite**: `MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` updates on edited
  files; `docs/knowledge-graph.xml` removes `TaskContext` annotations from
  `M-DOMAIN-MODEL`. `scripts/grace_check.py` must pass.
- **SQL lint**: `uv run sqlfluff lint --dialect postgres --ignore-local-config --config
  pyproject.toml yascheduler/infra/persistence/sql` must pass after SQL edits.