# Design: drop-task-context-entity

## Context

`yascheduler_tasks` currently stores its domain state in a single `metadata JSONB`
column. The domain layer wraps that JSONB in a `TaskContext` value object accessed via
`task.context.X`, with `to_metadata` / `from_metadata` as the serialization boundary.
The post-009 schema (committed at `d7fc8b3`) cleaned up `title`, `status` enum, and
timestamps; this change continues that cleanup into the `metadata` blob.

Constraints inherited from the proposal (frozen):
- Public surface preserved: `queue_get_tasks*` dict shape, `Yascheduler` API, CLI,
  INI config, AiiDA entrypoint.
- Python >=3.9, no new dependencies.
- Migration 010 targets the post-009 schema; `last_migration '009' → '010'`.
- sqlfluff (not sqlruff) lints the SQL after edits.

## Goals

- Extract six typed keys out of `metadata` JSONB into proper columns; route the
  remainder (input-file payloads and any future extras) into a new `extra` JSONB.
- Dissolve `TaskContext` / `TaskContextOverrides` and fold their fields/methods into
  `Task` / `NewTask`.
- Make the two real post-extraction mutation sites (`submit_task` remote-folder
  assignment, `consume_task` download-results update) explicit named methods on `Task`.
- Define a format contract for the new `error` column covering all three write sites,
  preserving existing behavior including the mixed permanent+transient case.
- Preserve the `queue_get_tasks*` facade dict shape exactly.

## Non-Goals

- Reformatting legacy `error` values stored in existing rows (migration passes them
  through verbatim; only new writes follow the contract).
- Normalizing the two bare-string error sites (`"unsupported engine"`,
  `"node is gone"`) — they are already human-readable and unchanged.
- Indexing or filtering on the new typed columns — a future change can add indexes if
  query patterns demand it; this change is structural only.
- Touching the `TaskRepository` port (`domain/ports.py`) — its interface is unaffected
  (the port already abstracts over the row shape via `Task`).
- Refactoring tests for design reasons — tests are updated only to compile and pass
  against the new model; per user, test changes are not a design blocker.

## Decisions

### D1 — Typed columns + `extra` JSONB (vs. keep `metadata` or split further)

Seven new columns: six typed (`engine`, `remote_folder`, `local_folder`,
`webhook_url`, `error`, `webhook_custom_params`) plus one catch-all `extra` JSONB.

**Why typed for the six**: they are the fields read at specific call sites
(`deployment.py`, `check_status.py`, `consume_task.py`, `submit_task.py`, event
construction) — typed access removes the `task.context.X` hop and makes the schema
self-describing. VARCHAR lengths follow repo convention: `engine VARCHAR(64)` (engine
names are short identifiers), `remote_folder` / `local_folder VARCHAR(1024)` (absolute
paths), `webhook_url VARCHAR(2048)` (URLs), `error TEXT` (unbounded — failure messages
of unknown length).

**Why `extra` JSONB for the rest**: input-file payloads (file contents as values,
file names as keys) are arbitrary-size and arbitrary-shape — they cannot be typed
without a schema for every engine's inputs. `extra` is the honest carrier. It also
absorbs any future metadata keys without a migration, preserving the flexibility that
`metadata` JSONB originally offered.

**Alternative considered**: split `extra` further (e.g. dedicated `inputs` JSONB).
Rejected — YAGNI; nothing reads `extra` as a structured sub-object today, only
`task.context.extra[input_file]` at `deployment.py:135` reads individual keys. One
JSONB bucket is enough until a second consumer appears.

### D2 — Fold `TaskContext` into `Task` (vs. keep `TaskContext`)

`TaskContext` existed only to model the `metadata` JSONB as a value object. Once the
JSONB is gone, the value object has no reason to exist — its fields are the task's
fields. Folding eliminates an indirection that every read paid for zero behavioral
benefit.

**Alternative considered**: keep `TaskContext` as a pure-Python aggregate even with
typed columns. Rejected by the user explicitly ("TaskContext не является публичным
API и нет проблемы его удалить").

### D3 — Explicit methods `with_remote_folder` + `with_download_results` (vs. typed `replace(**overrides)`)

Variant A proposed a `TaskOverrides` TypedDict plus a typed `replace(**overrides)`
method. Rejected as YAGNI: only two real mutation sites exist post-extraction, and
named methods express intent better than a generic replace-with-overrides.

- `with_remote_folder(self, remote_folder: str) -> Task` — submit-time, after insert
  generates the task id and the remote path is constructed.
- `with_download_results(self, *, local_folder: str, remote_folder: str) -> Task` —
  consume-time, after `download_outputs` returns. `extra` is NOT updated by this
  method: after extraction `extra` carries only input-file payloads, and the download
  path never touches them.

**Key insight strengthening this decision**: the existing `extra_updates` merge block
in `consume_task._decide_finalisation` (L117-126) builds `extra_updates = {k: v for k,
v in meta_dict.items() if k not in ("remote_folder", "local_folder", "error")}`. The
keys that can ever appear in `meta_dict` are exactly: `remote_folder` / `local_folder`
(appended by `download_outputs` at download.py:85-88) and `error` (appended by
`_decide_finalisation` itself at consume_task.py:114). `extra_updates` is therefore
always an empty dict in practice; the whole merge block is a no-op and is deleted.
This is the strongest argument for `with_download_results` ignoring `extra`: the
download path demonstrably never modified `extra`.

`with_download_results` is called with possibly-same values (the call site falls back
to the existing field when `meta_dict.get(...)` returns falsy). The method expresses
intent (this is the post-download update), not a delta — accepted, not worth further
documentation.

**Implementation follow-up (meta_add removal):** the original `download_outputs`
returned `(meta_add: list[tuple[str, Any]], transient_errors, permanent_errors)`,
where `meta_add` carried `[("remote_folder", remote_dir), ("local_folder",
str(local_dir))]`. This list-of-pairs was a metadata-blob relic: `consume_task`
rebuilt a `meta_dict` from it only to read the two keys back. As a follow-on
cleanup during implementation, the contract was simplified to a 4-tuple
`(local_folder: str, remote_folder: str, transient_errors, permanent_errors)`
— the two paths flow directly to `_decide_finalisation` / `_finalize_task` as
named parameters, and the `meta_dict` reconstruction is gone. The two
`local_folder=local_folder or task.local_folder or ""` / `remote_folder=
remote_folder or task.remote_folder or ""` fallbacks in `_decide_finalisation`
preserve the prior semantics (download-supplied value wins, existing field
fills the gap, empty string if both empty).

### D4 — `error` column format contract

Three write sites, three shapes:

| site | value |
| --- | --- |
| `allocate_task` reject | `"unsupported engine"` (bare) |
| `orchestrator` fail | `"node is gone"` (bare) |
| `consume_task` download fail | `"Download error: <path>: <msg>, <path>: <msg>"` |

The download format combines `permanent_errors + transient_errors` exactly as today
(Option α — user chose to preserve current behavior in the mixed case). Entries with
`path=None` render as bare `"<msg>"`, though in practice `path` is always a string
(download.py appends `(remote_dir, err)` for the catch-all, and per-file entries use
the out_file path). `NULL` means no error (success path).

**Why a contract now**: the column is being born, so defining its write contract at
creation is the natural moment. No reader parses the string — e2e uses substring match
(`"No such file" in str(error)`), unit tests use bare strings, the webhook receives the
same `reason: str` on `TaskFailed`. So the format is for humans reading logs/DB rows.

**Migration behavior**: legacy `error` values (the old `str(error_map)` format, e.g.
`"{'/remote/1.out': 'No such file'}"`) are passed through verbatim by
`metadata->>'error'` extraction. The migration does not reformat existing rows; only
new writes follow the contract. This is acceptable because historical values are
read-only display data with no programmatic parser.

**Alternative considered (Option β)**: include only `permanent_errors` in the string,
dropping transient from the mixed case. Rejected by user — the current behavior
records the full history of the final attempt.

### D5 — Facade reconstruction in `_task_to_dict`

`_task_to_dict` (`client.py:89`) currently calls `t.context.to_metadata()`. Post-change
it reconstructs the flat `metadata` dict inline: typed fields with `None` omitted, then
`**extra` merged. The public dict shape `{task_id, label, status, metadata, node}` is
preserved exactly (package-facades spec). The `metadata` key stays a dict; only its
construction path changes.

### D6 — Migration 010 structure

```
ALTER TABLE yascheduler_tasks
  ADD COLUMN engine VARCHAR(64),
  ADD COLUMN remote_folder VARCHAR(1024),
  ADD COLUMN local_folder VARCHAR(1024),
  ADD COLUMN webhook_url VARCHAR(2048),
  ADD COLUMN error TEXT,
  ADD COLUMN webhook_custom_params JSONB,
  ADD COLUMN extra JSONB;

UPDATE yascheduler_tasks SET
  engine = COALESCE(metadata->>'engine', ''),
  remote_folder = metadata->>'remote_folder',
  local_folder = metadata->>'local_folder',
  webhook_url = metadata->>'webhook_url',
  error = metadata->>'error',
  webhook_custom_params = COALESCE(metadata->'webhook_custom_params', '{}'::jsonb),
  extra = COALESCE(
    metadata - 'engine' - 'remote_folder' - 'local_folder'
           - 'webhook_url' - 'error' - 'webhook_custom_params',
    '{}'::jsonb
  );

ALTER TABLE yascheduler_tasks
  ALTER COLUMN engine SET NOT NULL,
  ALTER COLUMN webhook_custom_params SET NOT NULL,
  ALTER COLUMN webhook_custom_params SET DEFAULT '{}'::jsonb,
  ALTER COLUMN extra SET NOT NULL,
  ALTER COLUMN extra SET DEFAULT '{}'::jsonb,
  DROP COLUMN metadata;
```

Notes:
- `->>` for the five string columns; `->` (arrow) for `webhook_custom_params` and
  `extra` to preserve JSONB type.
- `extra` subtracts the six known keys from `metadata` — whatever remains (input-file
  payloads) is the `extra` content. `COALESCE(..., '{}'::jsonb)` handles the
  `metadata IS NULL` edge case (should not occur post-009, but defensive).
- NOT NULL applied after backfill so the UPDATE can populate all rows first.
- Defaults on `webhook_custom_params` and `extra` are set so future inserts without
  explicit values get `'{}'::jsonb` (the domain layer always supplies explicit values,
  but the DB-level default is the safety net).

`schema.sql` updated to match the post-010 column set and `last_migration='010'`.

### D7 — SQL file column lists

`task/insert.sql`, `task/update_by_id.sql`, `task/get_by_id.sql`,
`task/list_by_status.sql`, `task/list_by_jobs.sql` all gain the seven new columns and
drop `metadata`. `update_meta.sql` is deleted (dead — zero callers in source and tests,
confirmed in explore round).

## Risks / Trade-offs

- **[Risk] Migration backfill correctness** — if any row has a `metadata` shape that
  drops a key the typed column expects (e.g. no `engine`), `COALESCE(..., '')` handles
  `engine`; other typed columns are nullable so a missing key yields NULL. `extra`
  captures the remainder regardless. **Mitigation**: the `COALESCE` defaults cover the
  known shapes; the migration runs after post-009 so `metadata` is well-formed by
  then. Integration test `test_migrations.py` already exercises the migration sequence
  and will catch regressions.
- **[Risk] `extra` grows unbounded** — input-file payloads are arbitrary-size. This is
  no regression (same as today's `metadata`), but `extra` has no length cap.
  **Mitigation**: accepted; JSONB is the right type for arbitrary-shape payloads. A
  future change can add size monitoring if it becomes operational pain.
- **[Risk] Public facade drift** — `_task_to_dict` reconstruction must exactly match the
  old `to_metadata()` output or `queue_get_tasks*` callers break.
  **Mitigation**: the package-facades spec pins the dict shape; the e2e
  `test_full_cycle.py` / `test_hetzner_live.py` assertions on the metadata dict content
  will catch any drift.
- **[Risk] Test churn hides a real regression** — many tests construct
  `Task(context=TaskContext(...))` and will be reshaped. **Mitigation**: user
  explicitly de-scoped test changes from design blocking; the tests are updated to the
  new shape and must pass, but test restructuring itself is not a design concern.
- **[Trade-off] Legacy `error` values keep the ugly `str(dict)` format** — historical
  rows display as `"{'/path': 'msg'}"` while new rows display as
  `"Download error: /path: msg"`. **Accepted**: no reader parses the string; the
  inconsistency is cosmetic and historical rows age out.

## Migration Plan

1. Apply migration 010 on a post-009 DB (additive columns + backfill + DROP metadata).
2. Deploy the updated application code (domain model + persistence + application +
   entrypoints). The code reads typed columns; the migration has already populated
   them.
3. No rollback path is provided beyond restoring the pre-010 DB backup — DROP COLUMN
  metadata is destructive. This matches the prior `task-schema-and-entity-cleanup`
  change's posture (migrations are forward-only).

## Open Questions

None. All resolved across the explore round(s): the four refinement threads
(`with_download_results` possibly-same values — not documented; `extra_updates`
always-empty → deleted; migration arrow-vs-text extraction; error format contract α)
and the retry→success→error=None confirmation are all captured above.