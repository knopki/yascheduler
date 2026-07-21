## Why

`openspec/specs/postgres-persistence/spec.md` (221 lines, 5 requirements, 13
scenarios) interleaves actual SHALL requirements with four content kinds that
GRACE assigns to code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 12 distinct
   instances enumerating absent code, dropped columns, or non-behavior as
   normative requirements:
   - `update_meta SQL is deleted (dead path removed)`
   - `The SQL SHALL NOT set ip (dropped)`
   - `The SQL SHALL NOT set updated_at (the BEFORE UPDATE trigger sets it)`
   - `The infrastructure layer SHALL NOT import TaskCreated directly`
   - `The row mapping SHALL NOT read a metadata column (the column is dropped)`
   - `The row mapping SHALL NOT construct a TaskContext (the value object is removed)`
   - `NewTask carries no allocated_node_id and no status`
   - `remote_folder and error are NOT on NewTask`
   - `created_at/updated_at are NOT bound`
   - `The hostname-keyed methods get(ip: str) and get_by_ips(ips: list[str]) are REMOVED`
   - `add_tmp is removed — there is no add_tmp method`
   - `The get(ip), get_by_ips, and add_tmp methods are removed`
   Every one describes a non-existent code path dressed up as a normative
   requirement — drift bait. The positive scenarios (`save raises
   TaskRowNotFoundError for missing task_id`, `insert returns Task with
   TaskCreated via materialize_task`, `Task rows always materialize with empty
   events`, `Row mapping wraps NodeId`, etc.) already capture the observable
   behavior; the negative-space prose restates them in inverse form.
2. **Design rationale living in the spec** — narrative answering *why the code
   is shaped this way*, including:
   - "pg8000 cannot adapt a `TaskId` dataclass" (the row-mapping
     `TaskId(int(row["task_id"]))` / `task_id.value` boundary rule);
   - "the `BEFORE UPDATE` trigger sets it" (justifying why `save`'s UPDATE
     does not bind `updated_at`);
   - "pg8000 adapts `dict` to JSONB natively; no `json.dumps` at the call
     site" (the `webhook_custom_params` / `extra` binding rule);
   - "if pg8000 returns them as a `str`, the row mapping SHALL `json.loads`
     them (defensive — pg8000's JSONB adaptation normally returns `dict`, but
     a str fallback path is preserved)" (the row-mapping defensive rule);
   - "the `NewTask.task_id` is ignored — none exists; the DB generates it"
     and "avoiding a second `get` round-trip" (the `insert` rationale);
   - "events are transient; the DB has no events column" and "only `insert`
     via `materialize_task` attaches `TaskCreated`" (the events-always-empty
     row-mapping rationale);
   - "the current `save` does not refresh the in-memory `Task`;
     `updated_at` is observable via the trigger on the next read" (the
     `update_by_id` RETURNING-only-`task_id` rationale);
   - "the allocator counts tmp rows toward `max_nodes` capacity" (the
     `list_all` returns-all-rows rationale);
   - "an `update` without `hostname` in `SET` would leave cloud nodes
     unreachable after daemon restart and excluded from `list_disabled`'s
     `WHERE hostname <> ''` filter (VM leak)" (the `update` SET-includes-
     hostname rationale);
   - "the returned `Node` carries the generated `node_id`, which is the
     tmp-node cleanup handle AND the real-node identity reused by
     `clouds.allocate`" (the `insert` RETURNING `node_id` rationale);
   - "the V1 cloud-allocation lifecycle relies on `update` to flip the tmp
     row's `hostname` from `""` (the NewNode default) to the real VM hostname
     in a single `UPDATE`" (a restatement of the same `update` rationale).
   Every piece belongs in `RATIONALE` / `INVARIANTS` on the owning
   `METHOD_*` region, not in spec.
3. **Implementation-level SQL/parameter-binding narrative** — the long
   per-method enumeration of which columns each UPDATE/INSERT binds, which
   columns the row-mapping reads, and which Python types the row-mapping
   constructs (`TaskId(int(row["task_id"]))`, `TaskStatus[row["status"]]`,
   `NodeId(int(row["allocated_node_id"])) else None`, the seven typed
   columns). The scenarios already assert the observable outcome
   (`insert returns Task with TaskCreated via materialize_task`, `Task rows
   always materialize with empty events`, `Row mapping wraps NodeId`, `Row
   mapping reads created_at and updated_at`, `Row mapping reads status as
   NodeStatus`); the parameter-by-parameter binding prose is the
   implementation's job and lives as `INVARIANTS` / `ENSURES` on the
   `METHOD_save` / `METHOD_insert` / `METHOD__row_to_task` /
   `METHOD__row_to_node` regions.
4. **Cross-capability duplication** — the `SQL file layout` requirement
   restates two contracts already owned by other capabilities:
   - "The schema DDL — the full latest snapshot (every `CREATE TABLE`
     includes all current columns; no inline `ALTER`s). The DO block's
     `last_migration` CONSTANT is the single manual edit point when a
     migration is added." — owned verbatim by the `postgres-schema-apply`
     capability (`Full latest snapshot with no inline ALTERs` and
     `Bootstrap DO block` requirements, with their own scenarios).
   - "Migration files — forward-only migration files (`{prefix_id}_{rest}.sql`
     or `.py`), applied by `apply_migrations` in string-sorted `prefix_id`
     order." — owned verbatim by the `db-migrations` capability
     (`Migrations directory and file format` and `Migration runner applies
     pending migrations sequentially` requirements, with their own
     scenarios).
   Keeping these paragraphs in `postgres-persistence` is drift bait the
   moment either sibling spec evolves; the only `postgres-persistence`-owned
   fact in the requirement is the task SQL file inventory and the cached
   `load_query` behavior.

In parallel, the code under `yascheduler/infra/persistence/` violates the
GRACE Python rule ("if an entity is annotated by markup, it must always be
wrapped in a region"): `UnitOfWorkNotInitializedError` in `exceptions.py`
is entirely unwrapped (its sibling `TaskRowNotFoundError` carries a
`CLASS_*` region; the UoW error does not); `_PgRepository` in `postgres.py`
carries an internal `METHOD__run` region but no enclosing `CLASS_*` region;
`_prefix_id` and `_rollback` in `postgres_migrations.py` are private
helpers but live outside any `FUNC_*` region — however
`postgres_migrations.py` is owned by the in-flight `db-migrations-spec-trim`
change, so it is out of scope here. Where `METHOD_*` regions exist in
`postgres.py` and `postgres_uow.py`, they hold `PURPOSE` only — the
rationale/invariants that should accompany the code is missing because it
currently sits in the spec.

## What Changes

- **MODIFIED `postgres-persistence`**: rewrite all 5 requirements to carry
  only behavioral contracts (SHALL statements + Gherkin scenarios). Remove
  the 12 invented `SHALL NOT` / "is removed" / "is REMOVED" enumerations of
  absent code, the parameter-by-parameter binding narrative on `save` /
  `insert` / row mapping, the design-rationale pieces listed above, and
  the two cross-capability duplicates (schema DDL + migration file format).
  Every observable behavioral scenario (13) survives unchanged. No
  requirement is added, removed, merged, or split; the 5 requirement
  headers stay identical so OpenSpec recognizes the MODIFIED operation.
- Wrap the missing `CLASS_*` regions required by the GRACE Python rule on
  the currently-unwrapped entities:
  - `CLASS_UnitOfWorkNotInitializedError` in
    `yascheduler/infra/persistence/exceptions.py` (its sibling
    `TaskRowNotFoundError` already has a `CLASS_*`; this change adds the
    matching one).
  - `CLASS__PgRepository` in `yascheduler/infra/persistence/postgres.py`
    (carries an internal `METHOD__run` region but no enclosing `CLASS_*`;
    the new `CLASS_*` closes after the nested `METHOD_*` `# endregion`).
- Enrich existing `MODULE_CONTRACT`, `CLASS_*`, and `METHOD_*` regions
  with the rationale/invariants/scope that leaves the spec, each in its
  correct GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
  - `INVARIANTS` carries conditions/contracts that always hold (e.g.
     `PostgresTaskRepository.save` binds 10 SET columns and never `ip` /
    `updated_at`; `webhook_custom_params` / `extra` are bound as Python
     dicts; `insert` binds `node_id=None` / `status=TaskStatus.TO_DO.name`;
     `_row_to_task` always sets `events=()` and never reads a `metadata`
     column or constructs a `TaskContext`; `PostgresNodeRepository` exposes
     no `get(ip)` / `get_by_ips` / `add_tmp` — node lookups use
     `get_by_id` / `get_by_ids` only and the tmp path uses `insert`;
     `list_all` returns ALL rows including tmp rows; `update` SET clause
     includes `hostname`).
  - `RATIONALE` is Q/A format only — why the entity/method is shaped this
    way (e.g. why `save` does not bind `updated_at` (the trigger sets it);
    why `insert` ignores `NewTask.task_id` (the DB generates it); why
    `update_by_id`'s RETURNING is `task_id`-only; why `list_all` returns
    tmp rows; why `update` MUST set `hostname` (the V1 cloud-allocation
    lifecycle); why pg8000 needs `task_id.value` / `node_id.value` not the
    dataclass (pg8000 cannot adapt dataclass instances)).
  - `SCOPE` declares the entity's functional boundaries with explicit
    `NOT:` exclusions where useful.
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`,
  no free-form labels. The spec's removed `SHALL NOT` sentences do NOT
  become a `SHALL NOT:` contract field — they become an `INVARIANTS` entry
  stating the positive contract, or a `RATIONALE` Q/A if the rationale is
  the valuable part.
- Every `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity
  — the `class` line (and any `@dataclass(...)` decorator), the docstring,
  every field, every `__init__` line, every `self.<attr>` assignment —
  through the trailing blank line before the next region marker. Every
  `METHOD_*` encloses the `async def` / `def` line, the body, and the
  trailing blank line. No region closes before its entity ends. The
  contract comment block (`# PURPOSE:`, `# INVARIANTS:`, etc.) sits
  INSIDE the region, above the entity's first line. Nesting is allowed:
  `METHOD_*` and inner `BLOCK_*` regions live INSIDE the enclosing
  `CLASS_*` region; the `CLASS_*` `# endregion` comes after the last
  nested `# endregion`.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `postgres-persistence`: requirements slimmed to SHALL statements and
  behavior scenarios; invented `SHALL NOT` / "is removed" negative-space
  language, parameter-binding narrative, row-mapping implementation detail,
  design rationale, and the schema-DDL/migration-file-format duplication
  already owned by `postgres-schema-apply` and `db-migrations` relocated
  out of the spec text and into GRACE code contracts across
  `yascheduler/infra/persistence/exceptions.py`,
  `yascheduler/infra/persistence/postgres_uow.py`,
  `yascheduler/infra/persistence/postgres.py`, and
  `yascheduler/infra/persistence/sql_loader.py`. No persistence behavior,
  DTO field, signature, scenario, SQL file, DB column, or public API is
  added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/postgres-persistence/spec.md` rewritten —
  every requirement trimmed to behavioral SHALL + scenarios; pre/post
  scenario count compared and MUST remain 13 → 13. `openspec validate
  --all --json` must still pass after the change. The schema DDL /
  migration file format content already lives in `postgres-schema-apply`
  and `db-migrations`; this change does NOT remove those specs' coverage
  of those topics — it removes the `postgres-persistence` restatement.
- **Code (markup only, no logic)**:
  - `yascheduler/infra/persistence/exceptions.py` — wrap
    `CLASS_UnitOfWorkNotInitializedError`; enrich `MODULE_CONTRACT` and
    the new `CLASS_*` with `INVARIANTS` + `RATIONALE`. Comment-only diff.
  - `yascheduler/infra/persistence/postgres_uow.py` — enrich
    `MODULE_CONTRACT`, `CLASS_PostgresUnitOfWork`, and the 7 `METHOD_*`
    regions with `INVARIANTS` / `RATIONALE` / `ENSURES` (executor
    single-worker invariant; UoW-not-initialized access pattern; commit
    dispatches events only after the DB COMMIT succeeds; rollback
    discards `_saved_tasks`; etc.). Comment-only diff.
  - `yascheduler/infra/persistence/postgres.py` — wrap `CLASS__PgRepository`
    around the existing `_PgRepository` class (closing after the nested
    `METHOD__run`); enrich `MODULE_CONTRACT`, the 2 `CLASS_*` repository
    regions, and all 16 `METHOD_*` regions with `INVARIANTS` /
    `RATIONALE` / `ENSURES` (parameter binding; row mapping; tmp-row
    INSERT; `hostname` always in `update` SET; no `get(ip)` / `add_tmp`;
    pg8000 needs `*.value` not dataclass; `dict` ↔ JSONB; events-always-
    empty; etc.). Comment-only diff.
  - `yascheduler/infra/persistence/sql_loader.py` — enrich
    `FUNC_load_query` with `ENSURES` (same string returned on every call
    with the same `name`; `.sql` files only) and `INVARIANTS` (the
    `_SQL_DIR` is `Path(__file__).parent / "sql"`, scoped to this
    package's bundled SQL directory). Comment-only diff.
  - `yascheduler/infra/persistence/db_config.py`,
    `migration_base.py`, `postgres_migrations.py`, `postgres_schema.py`
    are out of scope (owned by `config-value-objects-spec-trim`,
    `db-migrations-spec-trim`, and `postgres-schema-apply-spec-trim`
    respectively). No edits to those files in this change.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing unit and integration tests in
  `tests/unit/test_persistence_*` and `tests/integration/test_persistence_*`
  already assert them. A passing `uv run pytest -m unit` and `-m
  integration` run after the change is the regression guard.
- **Public surface**: none. No CLI command, console_script, INI config
  key, DB schema, public API, or log-format change in the diff. The diff
  is `# region` / `# endregion` markup + comment-field enrichment + spec
  text trim only.
- **Pilot scope**: this change ONLY dehydrates the `postgres-persistence`
  spec. Other specs (`postgres-schema-apply`, `db-migrations`,
  `use-cases`, `ssh-infrastructure`, etc.) are explicitly out of scope.
  Follows the pattern set by
  `2026-07-17-orchestrator-spec-dehydrate`,
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`,
  `2026-07-18-slim-domain-ports-spec`, `cloud-spec-trim`,
  `config-value-objects-spec-trim`, `db-migrations-spec-trim`, and the
  in-flight `orchestrator-spec-trim`, `e2e-testing-spec-trim`,
  `dependency-injection-spec-trim`, `logging-spec-trim`,
  `engine-config-parsing-spec-trim`, `package-facades-spec-trim`,
  `postgres-schema-apply-spec-trim`.
- **Non-goals**:
  - No change to any persistence behavior, SQL string, parameter binding,
    row mapping, repository method signature, or public API.
  - No spec split; all trimmed requirements remain in the
    `postgres-persistence` capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No edits to `db_config.py`, `migration_base.py`,
    `postgres_migrations.py`, `postgres_schema.py`, or `__init__.py` —
    those modules are owned by other in-flight trim changes or already
    have tight `MODULE_CONTRACT` regions; this change does not touch
    them.
  - No removal of any scenario; the 13 observable behavioral scenarios
    all survive.
