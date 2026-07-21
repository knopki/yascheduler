## Common rules for every code-touching task

Every code-touching task below obeys these invariants. They exist because a
prior attempt at a similar change was discarded specifically for violating
them.

- **GRACE fields are a closed set.** Allowed fields: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No invented fields. Specifically: no `SHALL NOT:`
  pseudo-field, no `EFFECTS:`, no `EXAMPLES:`, no `NOTES:`, no `RAISES:`,
  no free-form labels. The spec's removed `SHALL NOT` sentences do NOT become
  a `SHALL NOT:` contract field — they become an `INVARIANTS` entry stating
  the positive contract (e.g. "the runner is forward-only — no `down` /
  rollback path is provided"), or a `RATIONALE` Q/A if the rationale is the
  valuable part.
- **`RATIONALE` is Q/A format only**, answering "why is this entity shaped
  this way?". It is NOT a junk drawer for arbitrary prose, NOT a place to
  restate `PURPOSE`, NOT a place to dump the trimmed spec text verbatim. One
  Q and one A per item; multi-item allowed when there are distinct reasons.
- **`PURPOSE` answers WHY, not WHAT.** "Apply pending migrations from
  sql/migrations/" is WHAT and fails. "Bring the database schema and data
  forward to the latest migration on every deployment so the team ships
  incremental, replayable changes without manual DDL scripting" is WHY and
  passes. If the existing `PURPOSE` already answers WHY, leave it — do not
  churn for churn's sake.
- **Every `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity.**
  For a class: the `class` line, the docstring, every method, every
  `self.<attr>` assignment, through the trailing blank line before the next
  region marker. For a function: the `def` line, the entire body, any nested
  `BLOCK_*` regions, and the trailing blank line. A region that closes
  before its entity ends (e.g. wrapping only the contract comment block) is
  a defect. The contract comment block (`# PURPOSE:`, `# INVARIANTS:`, etc.)
  sits INSIDE the region, ABOVE the entity's first line; the `# region`
  marker opens the block, the contract fields follow, then the entity, then
  `# endregion`. Nesting is allowed: `BLOCK_*` regions live INSIDE the
  enclosing `FUNC_*` / `METHOD_*` / `CLASS_*` region; the outer `# endregion`
  comes after the last nested `# endregion`. The new `FUNC__rollback` in
  `postgres_migrations.py` encloses the existing `BLOCK_rollback` correctly
  (inner `# endregion BLOCK_rollback` first, then outer
  `# endregion FUNC__rollback`).
- **Comment-only diff.** No code logic, signature, decorator choice, docstring
  semantics, or import changes. Edits are `# region` / `# endregion` marker
  insertion and contract-field enrichment inside the marker block. Module
  docstrings (the first `"""..."""` after `# endregion MODULE_CONTRACT`) are
  NOT touched. The long internal narrative comment block inside
  `BLOCK_tracker_record` (in `_record_py_tracker`) stays as-is — it is
  in-region narrative that explains the non-obvious pg8000 autocommit
  behavior at the code site; the structured `RATIONALE` field duplicates the
  Q/A form for grep-ability, it does not replace the in-block narrative.

## 1. Apply the db-migrations spec delta

- [x] 1.1 Apply the 8 MODIFIED requirements from
  `openspec/changes/db-migrations-spec-trim/specs/db-migrations/spec.md` to
  `openspec/specs/db-migrations/spec.md`, replacing each original requirement
  block in place. Preserve requirement header text exactly
  (whitespace-insensitive match) so OpenSpec recognizes the MODIFIED
  operation. Headers to match (in spec order): `Migration runner applies
  pending migrations sequentially`, `SQL migrations execute as a
  multi-statement string`, `Python migrations use a Migration base class with
  injected dependencies`, `Python migration class discovery`, `Python
  migration tracker recording`, `Migrations directory and file format`,
  `Migration edit procedure`, `Migration system is forward-only`.
- [x] 1.2 Confirm the trimmed main spec contains zero `SHALL NOT` / `shall
  not` / `do NOT` / `does NOT` instances in requirement bodies (the 2
  enumerated in `proposal.md` Why § 1 are gone from the body; the
  corresponding scenarios `No down/rollback path` and `No generation tool`
  MUST stay). Confirm every observable behavioral scenario (`#### Scenario:`
  count) is preserved: pre 21 → post 21. Confirm the 6 rationale pieces
  enumerated in `proposal.md` Why § 2 are gone from the spec body (the
  `begin()` / `commit()` narrative paragraph on the `Migration` base class;
  the `Migration not required to be idempotent` body sentence — the matching
  scenario MUST stay; the pg8000 autocommit narrative in tracker recording;
  the `defensive guard` transient-`DatabaseError` retry narrative; the
  `prefix_id detection is the responsibility of a unit test ... NOT of the
  runner` layering sentence; the `Forgetting step 2 means ...` / `Forgetting
  step 3 means ...` / `These steps are a documented procedure; a unit test
  ... SHOULD exist` consequence prose on the edit procedure; the `Migrations
  are hand-written; the schema.sql snapshot is hand-maintained` aside on the
  forward-only requirement).
- [x] 1.3 `openspec validate --all --json` passes (exit 0). The change
  validates AND the trimmed main spec validates AND no other spec regresses
  (currently 20 specs + the in-flight change set).

## 2. yascheduler/infra/persistence/migration_base.py — enrich CLASS_Migration and MODULE_CONTRACT

The `CLASS_Migration` region already wraps the FULL class (the `class
Migration:` line, the docstring, `__init__`, `begin`, `commit`, `migrate`,
and the trailing blank line before EOF). The methods inside (`__init__`,
`begin`, `commit`, `migrate`) are short and stay WITHOUT their own
`METHOD_*` regions — the begin/commit rationale lives at the class level
because the four methods form one contract together. Only defined GRACE
fields are used; every `PURPOSE` answers WHY.

- [x] 2.1 Enrich existing `CLASS_Migration`: tighten `PURPOSE` to WHY if
  slipped (current text "Define the contract for Python-based migrations —
  inject config, connection, and logger so subclasses implement only the
  migration logic without wiring infrastructure." answers WHY — keep). Add
  `INVARIANTS` (stores `self.config`, `self.conn`, `self.log` exactly once
  in `__init__`; subclasses MUST override `migrate()` — the base raises
  `NotImplementedError`; `begin()` issues `BEGIN` on the wrapped connection
  via `self.conn.run("BEGIN")`; `commit()` issues `COMMIT` the same way; the
  pair exists for migrations needing non-transactional operations and is
  not used by transactional migrations). Add `RATIONALE` Q/A —
  Q1: why do `begin()` and `commit()` exist as helper methods when the
  runner already opens a transaction before calling `migrate()`?
  A1: certain PostgreSQL operations cannot run inside an open transaction
  (`CREATE INDEX CONCURRENTLY`, `VACUUM`, `REINDEX`); the intended pattern
  is `self.commit()` to close the runner's transaction, run the
  non-transactional command, then `self.begin()` to reopen a transaction
  before the runner records the tracker — without these helpers a migration
  could not safely perform such operations.
  Q2: why are migrations not required to be idempotent?
  A2: the `yascheduler_migrations` tracker guards against re-application —
  each `prefix_id` is applied at most once per database — so requiring
  idempotency would burden every migration with no payoff; the tracker
  invariant is the source of safety, not migration-level replay-safety.
- [x] 2.2 Tighten existing `MODULE_CONTRACT` `PURPOSE` to WHY if slipped
  (current text "Provide a minimal contract for Python-based migrations —
  inject config, connection, and logger so subclasses implement only the
  migration step without plumbing infrastructure." answers WHY — keep). Add
  `INVARIANTS` (the `Migration` base class is the sole public symbol of this
  module; `__init__` parameter order `(config, conn, log)` is fixed —
  `.py` migration files subclass and inherit this constructor without
  overriding it; module imports `pg8000.native.Connection` only under
  `TYPE_CHECKING` to avoid a hard runtime dependency from this thin base).
- [x] 2.3 Verify `uv run ruff check yascheduler/infra/persistence/migration_base.py`
  and `uv run ruff format --check yascheduler/infra/persistence/migration_base.py`
  pass; `uv run pytest -m unit tests/unit/test_migration_runner.py` is green.

## 3. yascheduler/infra/persistence/postgres_migrations.py — wrap FUNC__rollback, enrich MODULE_CONTRACT and all FUNC_* regions

The new `FUNC__rollback` region encloses the FULL function with the existing
`BLOCK_rollback` nested inside it (closing order: inner `# endregion
BLOCK_rollback` first, then outer `# endregion FUNC__rollback`). All other
existing `FUNC_*` regions already enclose their full functions; this task
only enriches the contract fields inside each region. `_prefix_id` (a
trivial 2-line helper) and `_MIGRATIONS_DIR` (a module-level constant) stay
unwrapped per the GRACE proportional rule. Only defined GRACE fields are
used; every `PURPOSE` answers WHY.

- [x] 3.1 Add `# region FUNC__rollback` ... `# endregion FUNC__rollback`
  enclosing the FULL function — the `def _rollback(conn: Connection) -> None:`
  line, the docstring/comment (if any), the body, the existing nested
  `BLOCK_rollback` region, and the trailing blank line. The contract block
  (`# PURPOSE:`, `# ENSURES:`) sits INSIDE the new region, above the `def`
  line. `PURPOSE` (WHY: drain the runner's open transaction on the failure
  path of every migration step so a half-applied migration does not leave
  a `BEGIN`-state transaction behind for the next migration to inherit).
  `ENSURES` (on call, issues `ROLLBACK` on the wrapped connection inside a
  `contextlib.suppress(Exception)` — best-effort: a connection-side failure
  during rollback is silenced because the caller is already on the exception
  path and will re-raise the original error).
- [x] 3.2 Enrich existing `MODULE_CONTRACT`: tighten `PURPOSE` to WHY if
  slipped (current text "Evolve the database schema and data forward in
  production — one migration per tracker-recorded transaction — so the team
  makes incremental, replayable changes without manual DDL scripting."
  answers WHY — keep). Update `SCOPE` to also state the runner is forward-
  only with explicit `NOT:` exclusions: `NOT: rollback / "down" path;
  NOT: migration generation tool; NOT: schema.sql generation tool; NOT:
  prefix_id uniqueness validation at runtime (a unit-test responsibility)`.
  Add `INVARIANTS` (the migration system is forward-only — once a row is
  recorded in `yascheduler_migrations`, the runner never deletes it and
  never reverses the migration; the runner does not validate `prefix_id`
  uniqueness across files — a unit test scanning the migrations directory
  asserts uniqueness; the `schema.sql` snapshot and individual migration
  files are hand-written, no tool generates either; `apply_migrations` is
  synchronous and opens a single pg8000 connection for the whole run).
  Add `RATIONALE` Q/A —
  Q1: why is the migration system forward-only with no `down` / rollback
  path? A1: rolling back a migration in production typically requires
  data-loss decisions the runner cannot make (a column add cannot be
  reversed without dropping the column and its data; a data backfill
  cannot be reversed without the pre-image); the project ships a new
  forward migration to fix a bad one, and the `yascheduler_migrations`
  tracker row is the audit log of what landed.
  Q2: why does the runner not validate `prefix_id` uniqueness at runtime?
  A2: a duplicate `prefix_id` is a static authoring defect — surfacing it
  via a unit test that scans the migrations directory gives the author
  feedback at CI time before the migration reaches any database, and keeps
  the runner's job (apply pending migrations) narrow.
  Q3: why is there no migration generation tool? A3: every migration in
  this project is small, schema-anchored, and hand-reviewed against the
  `schema.sql` snapshot (the `Migration edit procedure` requirement);
  auto-generation would couple the project to a schema-diff tool and
  bypass the human review that the snapshot-conformance step enforces.
- [x] 3.3 Enrich existing `FUNC__scan_migrations`: tighten `PURPOSE` to WHY
  if slipped (current text "Discover all available migration files so the
  runner can determine which ones need applying, in filename order." is
  borderline WHAT — replace with a WHY statement such as "Hand the runner
  the complete, filename-sorted list of `.sql` and `.py` migration files so
  it can compute the pending set without re-globbing the directory per
  step"). Add `INVARIANTS` (returns paths sorted by `Path.name` string
  comparison — same key the runner uses for `prefix_id` ordering; scans
  `_MIGRATIONS_DIR` for both `*.sql` and `*.py` files; the returned list is
  a fresh `list` each call — no caching across `apply_migrations`
  invocations).
- [x] 3.4 Enrich existing `FUNC__last_applied`: tighten `PURPOSE` to WHY if
  slipped (current text "Determine the last successfully applied migration
  so the runner applies only newer files and avoids re-executing
  already-recorded steps." answers WHY — keep). Keep `ENSURES`; add
  `INVARIANTS` (runs `SELECT MAX(migration_id) FROM yascheduler_migrations`
  and returns `str(rows[0][0])` — the tracker stores `prefix_id` strings,
  so the comparison is lexicographic, matching the filename sort; the
  `try/except DatabaseError` is defensive — `apply_schema` is contractually
  run before `apply_migrations` and creates the tracker, but the except
  branch treats an absent tracker as `None` ("apply all") rather than
  crashing; `apply_migrations` is therefore robust to a manually-dropped
  tracker on a database that has no migrations applied yet).
- [x] 3.5 Enrich existing `FUNC__pending`: tighten `PURPOSE` to WHY if
  slipped (current text "Compute the set of not-yet-applied migrations so
  the runner applies only what is needed, preserving chronological order."
  answers WHY — keep). Add `INVARIANTS` (returns the full input list when
  `last is None` — fresh database, every migration is pending; otherwise
  filters by `_prefix_id(f) > last` — lexicographic comparison on the
  before-first-`_` token, matching the filename sort key; preserves the
  sorted order of the input list — no re-sort).
- [x] 3.6 Enrich existing `FUNC__one_migration_subclass`: tighten `PURPOSE`
  to WHY if slipped (current text "Extract the single Migration subclass
  from a .py migration file so the runner can call migrate() — fails loud
  on ambiguous or empty files to prevent silent skips." answers WHY —
  keep). Add `INVARIANTS` (uses `inspect.getmembers(module, inspect.isclass)`
  filtered to `issubclass(cls, Migration) and cls is not Migration and
  cls.__module__ == module.__name__` — imported `Migration` re-exports and
  unrelated `Migration` subclasses from other modules are NOT counted;
  candidate count MUST be exactly 1, otherwise raises `RuntimeError` with
  a message naming `module.__file__` and the candidate count). Add
  `RATIONALE` Q/A — Q: why filter by `cls.__module__ == module.__name__`
  in addition to `issubclass(cls, Migration)`? A: a `.py` migration file
  typically imports `from yascheduler.infra.persistence.migration_base
  import Migration` to declare its subclass — without the `__module__`
  filter, `Migration` itself would appear as a class in the module and
  pollute the candidate list; filtering to classes defined locally to the
  migration file keeps the discovery exact.
- [x] 3.7 Enrich existing `FUNC__apply_sql_migration`: tighten `PURPOSE` to
  WHY if slipped (current text "Execute a .sql migration file atomically and
  record it in the tracker so the schema evolves safely and re-runs are
  prevented." answers WHY — keep). Add `INVARIANTS` (issues `BEGIN` then
  `conn.run(path.read_text())` — the file text is executed as a
  multi-statement string in one round-trip, mirroring `psql`'s default
  behavior; the tracker `INSERT` runs inside the same transaction as the
  SQL body so a schema change and its tracker record commit atomically).
  Add `ENSURES` (on success, a row `(<prefix_id>, <default-timestamp>)`
  exists in `yascheduler_migrations` and the migration's SQL is committed;
  on any error from `BEGIN` through `COMMIT`, issues best-effort `ROLLBACK`
  via `_rollback(conn)` and re-raises — no tracker row is inserted for the
  failed migration).
- [x] 3.8 Enrich existing `FUNC__record_py_tracker`: tighten `PURPOSE` to
  WHY if slipped (current text "Persist the tracker record for a .py
  migration after migrate() succeeds so the same step is never re-applied,
  even if the runner crashes after the SQL landed." answers WHY — keep).
  The long internal narrative comment block inside the existing
  `BLOCK_tracker_record` stays as-is — it explains the non-obvious pg8000
  autocommit behavior at the code site. Add `INVARIANTS` outside the BLOCK
  but INSIDE the FUNC region (issues `INSERT INTO yascheduler_migrations
  (migration_id) VALUES (:p)` then `COMMIT`; on `DatabaseError`, reopens
  with `BEGIN` and retries the `INSERT` / `COMMIT` exactly once — the retry
  path handles transient DB-side errors like a deadlock on the tracker
  table; a non-transient failure such as a duplicate-`prefix_id` primary-
  key violation re-raises from the retry and surfaces the real defect).
  Add `ENSURES` (on success, the row `(<prefix_id>, <default-timestamp>)`
  exists in `yascheduler_migrations`; works in BOTH the normal case —
  migrate's transaction still open, the INSERT/COMMIT commits inside it —
  and the commit-closed case — migrate called `self.commit()` and did not
  reopen, the INSERT autocommits and the trailing COMMIT is a no-op
  warning rather than an error). Add `RATIONALE` Q/A —
  Q1: why does the tracker record succeed in BOTH the normal case and the
  `self.commit()`-closed case? A1: pg8000 native AUTOCOMMITS statements
  issued outside an open transaction, and a bare `COMMIT` with no open
  transaction is a no-op warning rather than an error — so a Python
  migration that legitimately closed the runner's transaction for a
  non-transactional operation (`CREATE INDEX CONCURRENTLY`, `VACUUM`) is
  still tracker-recorded; the contract is "migrate() applied <=> tracker
  recorded".
  Q2: why does the function retry the INSERT/COMMIT once on
  `DatabaseError`? A2: the retry is a defensive guard for transient DB-
  side errors on the tracker record (e.g. a deadlock between two
  concurrent `yainit` invocations); the reopen-and-retry turns a transient
  conflict into a success, while a non-transient failure (duplicate-
  `prefix_id` PK violation) re-raises from the retry and lets the caller's
  `ROLLBACK` handle it.
- [x] 3.9 Enrich existing `FUNC__apply_py_migration`: tighten `PURPOSE` to
  WHY if slipped (current text "Execute a Python migration step inside a
  transaction — load the module, call migrate(), and record the tracker —
  so complex DDL/DML logic runs safely and is never re-applied." answers
  WHY — keep). Add `INVARIANTS` (loads the migration module from `path` via
  `importlib.util.spec_from_file_location(prefix_id, path)` — the prefix_id
  is the module name, so a `.py` migration file is importable only by the
  runner, not by regular `import` statements; raises `RuntimeError` if the
  spec or loader is `None`; the runner opens `BEGIN` BEFORE loading the
  module, so a module-level statement that touches the DB (rare but legal)
  runs inside the migration's transaction). Add `ENSURES` (on success,
  the migration's `migrate()` body has run AND the tracker row for
  `<prefix_id>` is recorded (the tracker recording is delegated to
  `_record_py_tracker`); on any error from module load, `migrate()`, or
  tracker recording, issues best-effort `ROLLBACK` via `_rollback(conn)`
  and re-raises — no tracker row is inserted for the failed migration).
- [x] 3.10 Enrich existing `FUNC_apply_migrations`: tighten `PURPOSE` to
  WHY if slipped (current text "Apply all pending schema/data migrations in
  forward order so the database is up-to-date on every deployment without
  manual SQL intervention." answers WHY — keep). Add `REQUIRES` (`config`
  is a validated `PostgresDbConfig` with a reachable database; the
  database already has the `yascheduler_migrations` tracker table —
  `apply_schema` runs first in `yainit` and in test fixtures). Add
  `INVARIANTS` (synchronous — opens ONE pg8000 `Connection` for the whole
  run and closes it in `finally`; pending list is computed once from
  `_last_applied` + `_scan_migrations` + `_pending` — the directory is NOT
  re-scanned per migration; dispatches on `path.suffix` — `.sql` files
  route to `_apply_sql_migration`, everything else routes to
  `_apply_py_migration`; the runner does NOT validate `prefix_id`
  uniqueness at runtime — that is a unit-test responsibility; the runner
  does NOT delete tracker rows nor reverse applied migrations — the
  system is forward-only). Add `ENSURES` (on success, every file in the
  pending list has a tracker row; on failure, the failing migration's
  tracker row is NOT inserted and the error propagates out of
  `apply_migrations` — the connection is closed in `finally` regardless).
- [x] 3.11 Verify
  `uv run ruff check yascheduler/infra/persistence/postgres_migrations.py`
  and `uv run ruff format --check yascheduler/infra/persistence/postgres_migrations.py`
  pass; `uv run pytest -m unit tests/unit/test_migration_runner.py` and
  `uv run pytest -m integration tests/integration/test_migrations.py tests/integration/test_migration_012_node_rename.py tests/integration/test_migration_013_ncpus_nullable.py tests/integration/test_allocated_node_id_migration.py`
  is green (assume Docker running).

## 4. End-to-end verify

- [x] 4.1 Manual scan: every `# region CLASS_*`, `FUNC_*`, `BLOCK_*`, and
  `MODULE_CONTRACT` in `yascheduler/infra/persistence/migration_base.py`
  and `yascheduler/infra/persistence/postgres_migrations.py` has a paired
  `# endregion` and wraps the entire entity. No orphaned trailing code
  outside the region; no region closes before its entity ends. The new
  `FUNC__rollback` in `postgres_migrations.py` correctly encloses the
  existing `BLOCK_rollback` — the inner `# endregion BLOCK_rollback` comes
  BEFORE the outer `# endif FUNC__rollback`. `CLASS_Migration` in
  `migration_base.py` continues to enclose the FULL class body including
  the docstring and every method. The methods inside (`__init__`, `begin`,
  `commit`, `migrate`) intentionally do NOT have their own `METHOD_*`
  regions — the four methods form one contract documented at the class
  level via `INVARIANTS` / `RATIONALE`.
- [x] 4.2 Manual scan: no invented GRACE field names anywhere in the
  touched files — only `PURPOSE` / `SCOPE` / `INVARIANTS` / `USECASES` /
  `DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` / `ENSURES`.
  Specifically, NO `SHALL NOT:` field, NO `RAISES:` field, NO `EFFECTS:`
  field, NO `EXAMPLES:` field, NO `NOTES:` field anywhere.
- [x] 4.3 Manual scan: every `PURPOSE` field answers WHY, not WHAT.
  Spot-check `MODULE_CONTRACT` and every `CLASS_*` / `FUNC_*` region in
  `yascheduler/infra/persistence/migration_base.py` and
  `yascheduler/infra/persistence/postgres_migrations.py`. Where the
  existing `PURPOSE` already answers WHY, leave it.
- [x] 4.4 Manual scan: every `RATIONALE` field is in Q/A format
  ("Q: ... A: ..."). No `RATIONALE` block contains free-form prose that
  should be in `PURPOSE` / `INVARIANTS` / `SCOPE`. Specifically, the
  begin/commit pattern and the idempotency rationale live as Q/A pairs
  inside `CLASS_Migration.RATIONALE`; the autocommit and transient-retry
  rationale live as Q/A pairs inside
  `FUNC__record_py_tracker.RATIONALE`; the forward-only / uniqueness /
  no-generation-tool rationale live as Q/A pairs inside
  `MODULE_CONTRACT.RATIONALE` of `postgres_migrations.py`; the
  `cls.__module__ == module.__name__` filter rationale lives as a Q/A
  inside `FUNC__one_migration_subclass.RATIONALE`.
- [x] 4.5 `openspec validate --all --json` passes (exit 0); the trimmed
  `db-migrations` spec validates AND the change `db-migrations-spec-trim`
  validates AND no other spec regresses.
- [x] 4.6 `uv run pytest -m unit` — all unit tests pass (no behavior
  changed; the existing 21 scenarios in
  `tests/unit/test_migration_runner.py` already assert them).
- [x] 4.7 `uv run pytest -m integration` — all integration tests pass
  (assume Docker running).
- [x] 4.8 `uv run ruff check .` and `uv run ruff format --check .` pass on
  all changed files.
- [x] 4.9 `uv run lint-imports` passes (no new imports introduced;
  markup-only edits).
- [x] 4.10 Confirm no public-surface change: no CLI command,
  console_script, INI config key, DB schema, public API, migration file
  format, or log-format change in the diff. The diff is
  `# region` / `# endregion` markup + comment-field enrichment + spec
  text trim only.
