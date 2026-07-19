## Why

`openspec/specs/db-migrations/spec.md` (205 lines, 8 requirements, 21 scenarios)
interleaves actual SHALL requirements with three content kinds that GRACE
assigns to code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 2 distinct
   instances enumerating absent code or non-behavior as normative requirements,
   both in the `Migration system is forward-only` requirement:
   - `the runner ... SHALL NOT provide a migration rollback ("down") path, a
     migration generation tool, or a schema.sql generation tool`
   - `Once a migration is recorded in yascheduler_migrations, the runner SHALL
     NOT delete that tracker row or reverse the migration`
   Each one is already asserted by a Gherkin scenario (`No down/rollback path`,
   `No generation tool`) — the body prose restates the scenarios in
   negative-space form and is drift bait.
2. **Design rationale living in the spec** — 6 distinct pieces that answer
   *why the code is shaped this way*:
   - the `begin()` / `commit()` narrative on the `Migration` base class
     ("exist for migrations needing non-transactional operations ... the
     intended pattern is `self.commit()` ... then `self.begin()` to reopen a
     transaction");
   - the `Migration` "not required to be idempotent" body sentence (the
     `Migrations are not required to be idempotent` scenario already captures
     the observable behavior — the tracker guards against re-application);
   - the pg8000 autocommit narrative in tracker recording ("statements issued
     outside an open transaction autocommit, so the `INSERT` autocommits and
     the trailing `COMMIT` is a no-op warning rather than an error");
   - the "defensive guard" transient-`DatabaseError` retry rationale in tracker
     recording;
   - the `Duplicate prefix_id detection is the responsibility of a unit test
     ... NOT of the runner. The runner applies migrations; it does not
     validate prefix_id uniqueness.` layering narrative;
   - the `Migration edit procedure` body's "Forgetting step 2 means ..." /
     "Forgetting step 3 means ..." / "These steps are a documented procedure;
     a unit test ... SHOULD exist to catch step 2 drift" consequence-and-
     enforcement narrative;
   - the `Migrations are hand-written; the schema.sql snapshot is
     hand-maintained` aside on the forward-only requirement (justifies the
     absent generation tool).
   Every piece belongs in `RATIONALE` / `INVARIANTS` on the owning entity,
   not in spec text.
3. **Implementation-level SQL narrative** — the `BEGIN` / `COMMIT` / `ROLLBACK`
   step-by-step wording on `SQL migrations execute as a multi-statement string`
   and on `Python migration tracker recording` describes HOW the runner
   serializes the transaction. The scenarios already assert the observable
   outcome (`SQL migration applies and is recorded`, `SQL migration failure
   rolls back and is not recorded`, `Normal Python migration records tracker
   atomically`, `Python migration with self.commit() still records tracker`,
   `Tracker INSERT retries on transient DatabaseError`, `Python migration
   failure rolls back and is not recorded`); the procedural SQL narrative is
   the implementation's job and lives as `ENSURES` / `INVARIANTS` on
   `_apply_sql_migration` / `_record_py_tracker`.

In parallel, the code under `yascheduler/infra/persistence/` violates the
GRACE Python rule ("if an entity is annotated by markup, it must always be
wrapped in a region"): `FUNC__rollback` in `postgres_migrations.py` carries
an internal `BLOCK_rollback` but no enclosing `FUNC_*` region — the block is
nested inside a function the region set never opens. Where regions exist
(`CLASS_Migration` in `migration_base.py`, the 8 `FUNC_*` regions in
`postgres_migrations.py`, the `MODULE_CONTRACT` of both files), they hold
`PURPOSE` (and a single `ENSURES` on `_last_applied`) only — the
rationale/invariants/scope that should accompany the code is missing because
it currently sits in the spec.

## What Changes

- **MODIFIED `db-migrations`**: rewrite all 8 requirements to carry only
  behavioral contracts (SHALL statements + Gherkin scenarios). Remove the 2
  invented `SHALL NOT` enumerations of absent code, the 6 design-rationale
  pieces listed above, the procedural SQL narrative, and the migration-edit
  consequence prose. Every observable behavioral scenario (21) survives
  unchanged. No requirement is added, removed, merged, or split; the 8
  requirement headers stay identical so OpenSpec recognizes the MODIFIED
  operation.
- Wrap the missing `FUNC__rollback` region required by the GRACE Python rule
  in `yascheduler/infra/persistence/postgres_migrations.py` (the existing
  inner `BLOCK_rollback` becomes correctly nested inside the new enclosing
  `FUNC_*`).
- Enrich existing `MODULE_CONTRACT`, `CLASS_Migration`, and the `FUNC_*`
  regions in `yascheduler/infra/persistence/migration_base.py` and
  `yascheduler/infra/persistence/postgres_migrations.py` with the
  rationale/invariants/scope that leaves the spec, each in its correct GRACE
  field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
  - `INVARIANTS` carries conditions/contracts that always hold (e.g.
    `apply_migrations` does not validate `prefix_id` uniqueness — that is a
    unit-test responsibility; the runner is forward-only; `_record_py_tracker`
    records the tracker in both the normal and the commit-closed cases).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g.
    why `begin()` / `commit()` exist on `Migration`; why migrations are not
    required to be idempotent; why the runner tolerates a closed transaction
    when recording the tracker; why the transient-`DatabaseError` retry
    exists; why `prefix_id` uniqueness is a test responsibility; why the
    migration system is forward-only with no generation tool).
  - `ENSURES` carries precise postconditions (e.g. tracker row inserted on
    success, `ROLLBACK` and re-raise on failure).
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no
  `NOTES:`, no `RAISES:`, no free-form labels. The spec's removed `SHALL NOT`
  sentences do NOT become a `SHALL NOT:` contract field — they become an
  `INVARIANTS` entry stating the positive contract (e.g. "the runner is
  forward-only — no `down`/rollback path is provided"), or a `RATIONALE` Q/A
  if the rationale is the valuable part.
- Every `CLASS_*` / `FUNC_*` / `METHOD_*` / `BLOCK_*` region encloses the
  FULL entity. For `CLASS_Migration`: the `class Migration:` line, the
  docstring, every method (`__init__`, `begin`, `commit`, `migrate`), through
  the trailing blank line before the next region marker. For each `FUNC_*`:
  the `def` line, the entire body, any nested `BLOCK_*` regions, and the
  trailing blank line. The new `FUNC__rollback` encloses the full function
  with the existing `BLOCK_rollback` nested inside (inner `# endregion`
  first, then the outer `# endregion`). A region that closes before its
  entity ends is a defect.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `db-migrations`: requirements slimmed to SHALL statements and behavior
  scenarios; invented `SHALL NOT` negative-space language, design rationale,
  the procedural SQL narrative, and the migration-edit consequence prose
  relocated out of the spec text and into GRACE code contracts across
  `yascheduler/infra/persistence/migration_base.py` and
  `yascheduler/infra/persistence/postgres_migrations.py`. No migration
  behavior, file format, tracker schema, `apply_migrations` signature,
  `Migration` subclassing contract, scenario, or public API is added,
  removed, or changed.

## Impact

- **Specs**: `openspec/specs/db-migrations/spec.md` rewritten — every
  requirement trimmed to behavioral SHALL + scenarios; pre/post scenario
  count compared and MUST remain 21 → 21. `openspec validate --all --json`
  must still pass after the change.
- **Code (markup only, no logic)**:
  - `yascheduler/infra/persistence/migration_base.py` — enrich
    `MODULE_CONTRACT`, `CLASS_Migration` with `INVARIANTS` / `RATIONALE`
    (begin/commit pattern; idempotency-not-required rationale).
  - `yascheduler/infra/persistence/postgres_migrations.py` — wrap the
    previously-unwrapped `FUNC__rollback` (existing `BLOCK_rollback` stays
    nested inside); enrich `MODULE_CONTRACT`, `FUNC__scan_migrations`,
    `FUNC__last_applied`, `FUNC__pending`, `FUNC__one_migration_subclass`,
    `FUNC__apply_sql_migration`, `FUNC__record_py_tracker`,
    `FUNC__apply_py_migration`, `FUNC_apply_migrations` with
    `INVARIANTS` / `ENSURES` / `RATIONALE`. No code logic, signature,
    decorator, docstring semantics, or import changes. Code contracts absorb
    what leaves the spec, comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing migration unit and integration tests
  (`tests/unit/test_migration_runner.py`, `tests/integration/test_migrations.py`,
  `tests/integration/test_migration_012_node_rename.py`,
  `tests/integration/test_migration_013_ncpus_nullable.py`,
  `tests/integration/test_allocated_node_id_migration.py`) already assert
  them. A passing `uv run pytest -m unit` and `-m integration` run after the
  change is the regression guard.
- **Public surface**: none. No CLI command, console_script, INI config key,
  DB schema, public API, migration file format, or log-format change in the
  diff. The diff is `# region` / `# endregion` markup + comment-field
  enrichment + spec text trim only.
- **Pilot scope**: this change ONLY dehydrates the `db-migrations` spec.
  Other specs (`postgres-schema-apply`, `postgres-persistence`, `cli`,
  `cloud`, `orchestrator`, etc.) are explicitly out of scope. Follows the
  pattern set by `2026-07-17-orchestrator-spec-dehydrate`,
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`,
  `2026-07-18-slim-domain-ports-spec`, the completed `cli-spec-trim`, and
  the in-flight `cloud-spec-trim` and `config-value-objects-spec-trim`.
- **Non-goals**:
  - No change to any migration behavior, file format, runner signature,
    `Migration` subclassing contract, `yascheduler_migrations` tracker
    schema, or `schema.sql` layout.
  - No spec split; all trimmed requirements remain in the `db-migrations`
    capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No markup additions to `yascheduler/infra/persistence/postgres_schema.py`
    (owned by the `postgres-schema-apply` capability, out of scope here) or
    to `yascheduler/entrypoints/cli/init.py` (owned by the `cli` capability,
    out of scope here) — even though both consume `apply_migrations`, the
    spec under trim is the migration runner/base/tracker contract only.
  - No markup additions to individual migration files in
    `yascheduler/infra/persistence/sql/migrations/` (those are runtime
    data files, not source code regions).
  - `FUNC__prefix_id` in `postgres_migrations.py` stays unwrapped — it is a
    trivial 2-line helper (`return filename.name.split("_", 1)[0]`); the
    GRACE proportional rule allows skipping trivial private one-liners.
