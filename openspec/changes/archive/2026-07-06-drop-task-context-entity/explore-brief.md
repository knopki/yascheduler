# Explore Brief — drop-task-context-entity

Source: prior explore session (see `docs/HANDOFF_drop_task_context_entity.md`) plus
follow-on refinement round in this session. All decisions converged; no open questions.

## Goal

Extract the `metadata` JSONB column of `yascheduler_tasks` into typed columns plus a
new `extra` JSONB, and dissolve the `TaskContext` domain entity by folding its fields
and methods into `Task` / `NewTask`. Public surface (`queue_get_tasks*` dict shape,
`Yascheduler` API, CLI commands, AiiDA entrypoint) unchanged.

## Rejected alternatives

- **Variant A — `TaskOverrides` TypedDict + typed `replace(**overrides)`**: YAGNI; only
  two real mutation ops exist post-extraction, named methods express intent better.
- **Keep `TaskContext`**: user wants it gone.
- **`remote_folder` / `error` on `NewTask`**: never set at construction in production;
  user explicitly removed.
- **TEXT for all columns**: user wants reasonable `VARCHAR(n)`; only `error` stays TEXT.
- **Nullable `engine` / `webhook_custom_params` / `extra`**: NOT NULL matches domain
  semantics.
- **Keep `update_meta.sql`**: dead (0 callers in source + tests), delete.
- **Format download error separately (Option β, permanent-only)**: user chose α — keep
  current behavior (permanent + transient combined) in the mixed case.

## Schema — `yascheduler_tasks` after migration 010

Existing columns unchanged: `task_id`, `title`, `status`, `allocated_node_id`,
`created_at`, `updated_at`.

| column                  | type            | null | default             | notes                          |
| ----------------------- | --------------- | ---- | ------------------- | ------------------------------ |
| engine                  | VARCHAR(64)     | NO   | —                   | migration sets `''` for legacy |
| remote_folder           | VARCHAR(1024)   | YES  | —                   |                                |
| local_folder            | VARCHAR(1024)   | YES  | —                   |                                |
| webhook_url             | VARCHAR(2048)   | YES  | —                   |                                |
| error                   | TEXT            | YES  | —                   | unbounded; NULL = no error     |
| webhook_custom_params   | JSONB           | NO   | `'{}'::jsonb`       |                                |
| extra                   | JSONB           | NO   | `'{}'::jsonb`       | carries input-file payloads    |
| metadata                | DROP            | —    | —                   | removed                        |

VARCHAR lengths match repo convention (`title VARCHAR(256)`, `username VARCHAR(255)`,
`cloud VARCHAR(32)`).

## Migration 010_extract_metadata_columns.sql

ADD 7 columns; UPDATE to extract from `metadata`:
- `engine = COALESCE(metadata->>'engine', '')`
- `remote_folder`, `local_folder`, `webhook_url`, `error` via `metadata->>'X'`
- `webhook_custom_params = COALESCE(metadata->'webhook_custom_params', '{}'::jsonb)`
  (arrow, not text — preserves JSONB)
- `extra = COALESCE(metadata - known_keys, '{}'::jsonb)` where `known_keys` is the 6
  typed field names
ALTER `engine` / `webhook_custom_params` / `extra` SET NOT NULL; DROP `metadata`.
Update `schema.sql` `last_migration '009' → '010'`.

Historical `error` values (legacy `str(dict)` format from the old download path) are
preserved verbatim by the migration — passthrough, no reformatting. New writes follow
the error column format contract (below).

## Domain model — `Task` / `NewTask` after change

DELETE: `TaskContext`, `TaskContextOverrides`, `_get_opt_str`, `to_metadata`,
`from_metadata`, `Task.with_context`.

### `Task` fields (frozen dataclass)

`task_id`, `label`, `engine`, `remote_folder`, `local_folder`, `webhook_url`,
`webhook_custom_params`, `error`, `extra`, `status`, `allocated_node_id`, `_events`,
`created_at`, `updated_at`. `engine` required, no default (after `label`); preserve
field-order rules.

### `NewTask` fields

Only fields used for `NewTask` in code; explicitly NO `remote_folder`, NO `error`:
`label`, `engine`, `local_folder`, `webhook_url`, `webhook_custom_params`, `extra`,
`status=TaskStatus.TO_DO`, `allocated_node_id=None`.

### Methods

- `Task.fail(reason) -> Task`: `replace(self, status=DONE, error=reason)` (simplified
  — no more nested `context.replace`).
- `Task.reject(reason) -> Task`: `replace(self, status=DONE, error=reason)`.
- `Task.with_event(...)`: reads `self.webhook_url`, `self.webhook_custom_params`
  (was `self.context.X`).
- `Task.with_remote_folder(self, remote_folder: str) -> Task`.
- `Task.with_download_results(self, *, local_folder: str, remote_folder: str) -> Task`:
  2 kwargs; `extra` NOT updated (per insight: extra no longer carries
  `local_folder` / `remote_folder` / `error` after extraction). Called with
  possibly-same values (fallback to existing) — method expresses intent, not delta;
  not worth documenting further.
- DELETE `Task.with_context`.

### Error column format contract

| write site                  | value                                                          |
| --------------------------- | ------------------------------------------------------------- |
| `allocate_task` reject      | `"unsupported engine"` (bare)                                 |
| `orchestrator` fail          | `"node is gone"` (bare)                                       |
| `consume_task` download fail | `"Download error: <path>: <msg>, <path>: <msg>"` (combined permanent + transient; entries with `path=None` → bare `"<msg>"`) |
| success                     | `NULL` (no write to `error`)                                  |

Column type `TEXT` nullable. Migration passes legacy values through unchanged; new
writes follow the contract. No reader parses the string — e2e uses substring match
(`"No such file" in str(error)`), unit tests use bare strings, webhook gets the same
`reason: str`.

## Facade preservation

`_task_to_dict` (`client.py:89`) reconstructs the flat metadata dict: typed fields with
`None` omitted, then `**extra` merged. Public `queue_get_tasks*` dict shape
`{task_id, label, status, metadata, node}` unchanged (package-facades spec).

## Cross-module data flows

### submit_task (application/submit_task.py:60-98)

```
metadata dict (caller) + engine_name
  → extract typed fields → NewTask(label, engine, local_folder, webhook_url,
                                    webhook_custom_params, extra)
  → uow.tasks.insert(new_task) → Task
  → task.with_remote_folder(remote_folder).with_event(TaskCreated, engine_name=task.engine)
  → uow.tasks.save(task) + commit
```

### consume_task (application/consume_task.py:94-142, 216-252)

```
task = uow.tasks.get(task_id)              ← reads typed fields
download_outputs(session, remote_dir, local_dir, files, task_id)
  → (meta_add, transient_errors, permanent_errors)
    meta_add only ever contains: ("remote_folder", ...), ("local_folder", ...),
                                   ("error", error_map) on failure
_decide_finalisation:
  - transient-only → return None (defer, no save, no event; DB error stays None)
  - else: combined_errors = permanent + transient
    - combined empty → .complete() (error untouched → None) → save
    - combined non-empty → _format_download_error(combined_errors)
                       → .fail(error_msg) (sets error) → save
                       → .with_event(TaskFailed, reason=error_msg)
```

The `extra_updates` merge block (consume_task.py:117-126) is a no-op in practice
(`meta_add` never carries keys outside `remote_folder`/`local_folder`/`error`) and
is deleted outright as part of this change — its removal is the strongest argument
for `with_download_results` ignoring `extra`.

### deployment / check_status (read-only context access)

`infra/ssh/operations/deployment.py:135,207,221` and
`entrypoints/cli/check_status.py:188-190,341,409` read `task.context.{extra,
remote_folder, engine, local_folder}` → become `task.{extra, remote_folder, engine,
local_folder}`. No logic change.

## Open questions

None. All resolved in explore round(s).